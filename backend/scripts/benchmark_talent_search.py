"""Opt-in replay through the real request preparation path; writes only usage logs.

Use an existing trace for its authorized user/base/provider, and --live to allow
model calls. Reports distinguish text fallback from working dense retrieval.
"""
import argparse
import json
from time import perf_counter
from app.db.session import SessionLocal
from app.db.models import AgentTraceModel,UserModel
from app.core.security import actor,usage_counter
from app.api.routes.knowledge import _prepare_ask
from app.schemas.knowledge import AskRequest
from app.services.talent_answer import PreparedTalentAnswer


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--trace-id',required=True)
    parser.add_argument('--query')
    parser.add_argument('--repeat',type=int,default=3)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if not args.live or not 1<=args.repeat<=5:parser.error('--live and repeat 1–5 required')
    report=[]
    with SessionLocal() as db:
        trace=db.get(AgentTraceModel,args.trace_id)
        if trace is None:parser.error('Trace not found')
        user=db.get(UserModel,trace.user_id)
        if user is None or not user.enabled:parser.error('Trace user unavailable')
        request=json.loads(trace.request_json)
        token=actor.set(user);db.info['actor']=(user.id,user.role)
        try:
            for i in range(args.repeat):
                counter={'dispatched':0,'calls':0,'tokens':0,'unknown':False}
                ct=usage_counter.set(counter);started=perf_counter()
                payload=AskRequest(question=args.query or trace.question,knowledge_base_id=trace.knowledge_base_id,
                    provider_id=request['provider_id'],model=request['model'],talent_search_mode='search')
                try:
                    _prepare_ask(payload,db)
                    raise RuntimeError('Expected personnel response')
                except PreparedTalentAnswer as answer:
                    response=answer.response
                    from app.services.talent_results import load_result,result_scope
                    from app.repositories.sqlite import KnowledgeIngestionRepository
                    sources=KnowledgeIngestionRepository(db).list_active_spreadsheet_sources(trace.knowledge_base_id)
                    scope=result_scope(db,trace.knowledge_base_id,sources)
                    state=response.query_state
                    snapshot=load_result(state.snapshot_id,scope,state.query,state.plan)
                    item={'iteration':i+1,'query':payload.question,'model':request['model'],
                        'elapsed_ms':round((perf_counter()-started)*1000),'model_calls':counter['dispatched'],
                        'returned':len(response.row_sources),'names':[r.fields.get('姓名') for r in response.row_sources],
                        'plan':state.plan,'retrieval':snapshot.get('retrieval') if snapshot else None,
                        'unresolved':snapshot.get('unresolved_conditions') if snapshot else None,
                        'matched':snapshot.get('matched') if snapshot else None}
                    report.append(item);print(json.dumps(item,ensure_ascii=False),flush=True)
                finally:usage_counter.reset(ct)
        finally:actor.reset(token)
    with open(args.output,'w') as output:json.dump(report,output,ensure_ascii=False,indent=2)


if __name__=='__main__':main()
