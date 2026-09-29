"""Health probe for cron/system monitoring. Emits nonzero exit status for alert integrations."""
import os
import urllib.request
url=os.environ.get('KNOWLEDGE_HEALTH_URL','http://127.0.0.1:8001/ready')
try:
    with urllib.request.urlopen(url,timeout=10) as response:
        if response.status!=200:raise RuntimeError('not ready')
    print('knowledge ready')
except Exception as exc:
    print('ALERT knowledge unavailable:',type(exc).__name__)
    raise SystemExit(1)
