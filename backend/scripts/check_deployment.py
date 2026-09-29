"""Authenticated read-only smoke/load probe; no model calls or data mutations.
Use --url for a staging deployment. Password comes from an interactive prompt.
"""
import argparse
import asyncio
import getpass
import json
import statistics
from time import perf_counter
import httpx

async def run(args):
    password=getpass.getpass('Password: ')
    async with httpx.AsyncClient(base_url=args.url,timeout=30,headers={'X-Requested-With':'knowledge-base'}) as client:
        response=await client.post('/api/auth/login',json={'username':args.username,'password':password});response.raise_for_status()
        gate=asyncio.Semaphore(args.concurrency)
        timings=[];statuses=[]
        async def one():
            async with gate:
                start=perf_counter();r=await client.get('/api/talents?page_size=30');timings.append((perf_counter()-start)*1000);statuses.append(r.status_code)
        await asyncio.gather(*(one() for _ in range(args.requests)))
        timings.sort()
        print(json.dumps({'requests':len(timings),'concurrency':args.concurrency,'p50_ms':statistics.median(timings),
            'p95_ms':timings[min(len(timings)-1,int(len(timings)*.95))],'statuses':{str(s):statuses.count(s) for s in set(statuses)}},indent=2))
        if any(s!=200 for s in statuses):raise SystemExit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:8001');p.add_argument('--username',default='admin')
    p.add_argument('--requests',type=int,default=20);p.add_argument('--concurrency',type=int,default=4)
    args=p.parse_args()
    if args.requests<1 or not 1<=args.concurrency<=32:p.error('Invalid request/concurrency count')
    asyncio.run(run(args))
