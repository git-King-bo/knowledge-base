"""Bounded network concurrency; budgets and database writes stay on the caller thread."""
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from app.ai.base import json_output_requested
from app.core.limits import claim_model_input, MAX_MODEL_CALLS_PER_OPERATION


def run_model_batch(adapter, provider, messages_batch, model, api_key, record):
    if len(messages_batch)>MAX_MODEL_CALLS_PER_OPERATION:
        raise ValueError('Verification wave exceeds operation call budget')
    def send(messages):
        # Executor threads do not inherit request ContextVars or database sessions.
        started=perf_counter()
        token=json_output_requested.set(True)
        try:
            return adapter._chat_reserved(provider,messages,model,api_key),None,int((perf_counter()-started)*1000)
        except Exception as exc:
            return None,exc,int((perf_counter()-started)*1000)
        finally:
            json_output_requested.reset(token)
    outputs=[]
    with ThreadPoolExecutor(max_workers=MAX_MODEL_CALLS_PER_OPERATION,thread_name_prefix='talent-verify') as pool:
        work=[]
        for messages in messages_batch:
            try:
                claim_model_input(messages)
            except Exception as exc:
                work.append((messages,None,exc))
                continue
            work.append((messages,pool.submit(send,messages),None))
        # Preserve reservation order when settling usage, including failed calls.
        for messages,future,error in work:
            if future is None:
                outputs.append(error)
                continue
            result,error,latency=future.result()
            record(messages,result,error,latency)
            outputs.append(error if error is not None else result.content)
    return outputs
