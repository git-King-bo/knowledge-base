"""Queue the standard durable field-index build; never create a separate summary index.

Run from backend with PYTHONPATH=. and --base-id. Start the backend normally to
consume these jobs. Its staging, batching, reuse and atomic publication apply.
"""
import argparse
import json
from app.db.session import SessionLocal
from app.repositories.sqlite import KnowledgeIngestionRepository
from app.services.import_jobs import enqueue,job_schema


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-id',required=True)
    # Accept old invocations, but preserve the shared worker's resource limits.
    parser.add_argument('--batch-size',type=int,default=None,help='Deprecated: batching is controlled by the backend worker')
    args=parser.parse_args()
    if args.batch_size is not None and not 1<=args.batch_size<=32:parser.error('batch size must be 1–32')
    with SessionLocal() as db:
        sources=KnowledgeIngestionRepository(db).list_active_spreadsheet_sources(args.base_id)
        if not sources:parser.error('No active spreadsheet sources in this knowledge base')
        jobs=[job_schema(enqueue(db,source.id,args.base_id)) for source in sources]
        print(json.dumps({'jobs':jobs,'message':'已提交统一字段索引任务，由运行中的后端处理；不再生成独立的人才摘要向量。'},ensure_ascii=False))


if __name__=='__main__':main()
