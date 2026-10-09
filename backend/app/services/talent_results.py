"""Short-lived, access-scoped result snapshots for stable pagination."""
from collections import OrderedDict
from copy import deepcopy
import json
import secrets
import threading
import time

_results=OrderedDict()
_lock=threading.Lock()
_TTL=600
_MAX_BYTES=16*1024*1024


def save_result(scope,question,plan,evidence):
    if scope is None:
        return None
    size=len(json.dumps(evidence,ensure_ascii=False).encode('utf-8'))
    if size>_MAX_BYTES:
        return None
    token=secrets.token_urlsafe(24)
    with _lock:
        for key in list(_results):
            if _results[key][0]<=time.monotonic():
                del _results[key]
        _results[token]=(time.monotonic()+_TTL,scope,question,deepcopy(plan),deepcopy(evidence),size)
        while len(_results)>16 or sum(value[-1] for value in _results.values())>_MAX_BYTES:
            _results.popitem(last=False)
    return token


def load_result(token,scope,question,plan):
    with _lock:
        item=_results.get(token)
        if not item or item[0]<=time.monotonic():
            _results.pop(token,None)
            return None
        if scope is None or item[1]!=scope or item[2]!=question or item[3]!=plan:
            return None
        _results.move_to_end(token)
        return deepcopy(item[4])


def result_scope(db,base_id,sources):
    from sqlalchemy import select
    from app.core.security import actor
    from app.db.models import SourceIndexModel
    user=actor.get()
    if not user:
        return None
    revisions={i.source_id:(i.revision,i.indexed_revision) for i in db.scalars(
        select(SourceIndexModel).where(SourceIndexModel.source_id.in_([s.id for s in sources])))}
    return (str(db.get_bind().url),user.id,base_id,tuple(sorted(
        (s.id,str(s.updated_at),s.status,revisions.get(s.id)) for s in sources)))


def result_page(evidence,offset,limit):
    from app.services.agent_trace import trace_note
    order=evidence['result_order']
    selected_order=order[offset:offset+limit]
    selected={tuple(key) for key in selected_order}
    for group in evidence['results']:
        if 'error' in group:
            continue
        group['records']=[row for row in group.get('records',[]) if (group['source_id'],group['sheet'],row['excel_row']) in selected]
        group['returned_records']=len(group['records'])
        group['truncated']=len(order)>offset+len(selected_order)
    evidence['result_order']=selected_order
    evidence['pagination']={'offset':offset,'page_size':limit,'returned':len(selected_order),
        'total':len(order),'has_more':offset+len(selected_order)<len(order)}
    trace_note('跨表排序与分页',**evidence['pagination'],matched=evidence['matched'])
    return json.dumps(evidence,ensure_ascii=False)


def sort_result(evidence,field,descending,scope,question,limit):
    """Sort the entire verified snapshot, never just its last displayed page."""
    from app.services.talent_search import number_value
    evidence=deepcopy(evidence)
    candidates=[]
    matched=0
    for group in evidence['results']:
        if 'error' in group:
            continue
        records=group.get('records',[])
        matched+=len(records)
        for row in records:
            value=number_value(str(row['fields'].get(field,'')))
            candidates.append((value,[group['source_id'],group['sheet'],row['excel_row']]))
    ranked=[item for item in candidates if item[0] is not None]
    ranked.sort(key=lambda item:item[0],reverse=descending)
    evidence.update(matched=matched,rankable=len(ranked),missing=matched-len(ranked),
                    unranked=bool(matched and not ranked),ranking_scope='previous_results')
    evidence['result_order']=[key for _,key in (ranked if ranked else candidates)]
    evidence['plan'].update(sort_by=field,descending=descending,limit=limit)
    evidence['snapshot_id']=save_result(scope,question,evidence['plan'],evidence)
    return result_page(evidence,0,limit)
