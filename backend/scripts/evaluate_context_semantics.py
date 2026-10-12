"""Opt-in live-model evaluation. Execution mocks are not semantic accuracy evidence."""
import argparse
import json
from pathlib import Path
from time import perf_counter

from app.ai.base import json_output_requested
from app.ai.registry import ai_provider_registry
from app.core.security import usage_counter
from app.db.session import SessionLocal
from app.repositories.sqlite import AIRepository
from app.schemas.ai import ChatMessage
from app.services.talent_search import TalentPlan,query_planner_instructions,parse_model_plan
from app.services.talent_context_update import inherit_plan,review_instructions,ContextChangeUnresolved


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Explicitly allow paid model calls (at most two per case)')
    parser.add_argument('--provider-id',required=True)
    parser.add_argument('--model')
    parser.add_argument('--cases',type=Path,default=Path('tests/evals/context_semantics.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.live:parser.error('--live is required; this is not a mocked unit test')
    cases=json.loads(args.cases.read_text())
    if not 1<=len(cases)<=20:parser.error('Use 1–20 cases per evaluation run')
    with SessionLocal() as db:
        record=AIRepository(db).get_provider_credentials(args.provider_id)
    if not record:parser.error('Provider not found')
    provider,key=record
    adapter=ai_provider_registry.resolve(provider.provider)
    report=[]
    for case in cases:
        counter={'dispatched':0}
        token=usage_counter.set(counter)
        started=perf_counter()
        item={'id':case['id'],'question':case['question'],'reviews':[],'usage':[]}
        def call(instructions,payload):
            if counter['dispatched']>=2:raise RuntimeError('Evaluation call budget reached')
            jt=json_output_requested.set(True)
            try:
                result=adapter.chat(provider,[ChatMessage(role='system',content=instructions),
                    ChatMessage(role='user',content=json.dumps(payload,ensure_ascii=False))],args.model or provider.default_model,key)
                item['usage'].append(result.usage.model_dump())
                return result.content
            finally:json_output_requested.reset(jt)
        def review(payload):
            raw=call(review_instructions(),payload)
            item['reviews'].append(json.loads(raw))
            return raw
        try:
            previous=TalentPlan.model_validate(case['previous'])
            raw=call(query_planner_instructions(),{'question':case['question'],
                'schema':{'fields':case['fields'],'domains':[]},
                'request_context':{'original_question':case['question'],'previous_plan':previous.model_dump()}})
            proposed=parse_model_plan(raw)
            item['proposed']=proposed.model_dump()
            if proposed.intent=='clarify':
                final=None
            else:
                try:final=inherit_plan(proposed,previous.model_dump(),case['question'],reviewer=review)
                except ContextChangeUnresolved:
                    if not item['reviews'] or item['reviews'][-1]['verdict']=='supported':raise
                    final=None
            expected=case['expected']
            checks={'clarification':(final is None)==expected.get('clarify',False)}
            if final is not None:
                item['resolved']=final.model_dump()
                checks.update({f'preserve_{i}':previous.evidence_conditions[i] in final.evidence_conditions for i in expected.get('retain',[])})
                checks.update({f'remove_{i}':previous.evidence_conditions[i] not in final.evidence_conditions for i in expected.get('remove',[])})
                checks['sort']=final.sort_by==expected.get('sort_by')
                facts=' '.join(final.evidence_conditions+[final.topic_condition])
                checks.update({f'contains_{term}':term in facts for term in expected.get('contains',[])})
                if 'topic' in expected:checks['topic']=expected['topic'] in final.topic_condition
            item.update(checks=checks,passed=all(checks.values()),executed=final is not None)
        except Exception as exc:
            item.update(passed=False,error=f'{type(exc).__name__}: {str(exc)[:300]}')
        finally:
            item.update(model_calls=counter['dispatched'],duration_ms=round((perf_counter()-started)*1000))
            usage_counter.reset(token)
        report.append(item)
        print(json.dumps({'id':item['id'],'passed':item['passed'],'checks':item.get('checks'),'error':item.get('error')},ensure_ascii=False),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'model':args.model or provider.default_model,'cases':len(report),
        'passed':sum(r['passed'] for r in report),
        'failed_executions':sum(not r['passed'] and r.get('executed',False) for r in report),
        'blocked_or_clarified':sum(not r['passed'] and not r.get('executed',False) for r in report),'results':report},ensure_ascii=False,indent=2)+'\n')
    return 0 if all(r['passed'] for r in report) else 1

if __name__=='__main__':raise SystemExit(main())
