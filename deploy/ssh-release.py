#!/usr/bin/env python3
"""GitHub 专用 SSH forced-command：只接受发布动作，不提供 Shell/SCP/端口转发。"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path('/opt/knowledge-base')


def main():
    command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
    match = re.fullmatch(r'kb-release (bootstrap|stage|promote|rollback|abort|status|retire)(?: ([a-z0-9][a-z0-9.-]{0,39}))?', command)
    if not match:
        raise ValueError('Only kb-release deployment commands are permitted')
    action, version = match.groups()
    controller = ['python3', str(ROOT / 'deploy/release.py')]
    if action in ('bootstrap', 'stage'):
        # 只读有限长度的 JSON，绝不把客户端输入作为 shell 脚本执行。
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValueError('Payload too large')
        payload = json.loads(raw)
        if payload['manifest']['version'] != version:
            raise ValueError('Manifest version mismatch')
        with tempfile.TemporaryDirectory(prefix='kb-registry-') as folder:
            env = dict(os.environ, DOCKER_CONFIG=folder)
            username = payload['registry_user']
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', username):
                raise ValueError('Invalid registry account')
            # 临时 GITHUB_TOKEN 仅用于此次 pull；临时 Docker 凭据随任务删除。
            subprocess.run(['docker', 'login', 'ghcr.io', '-u', username, '--password-stdin'],
                           input=payload['registry_token'], universal_newlines=True, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            manifest = Path(folder) / 'manifest.json'
            manifest.write_text(json.dumps(payload['manifest']))
            if action == 'bootstrap':
                subprocess.run(controller + ['bootstrap', str(manifest)], env=env, check=True)
                return
            subprocess.run(controller + ['register', str(manifest)], env=env, check=True)
        # 发布前停掉历史闲置容器，但保留 active/candidate 和镜像历史。
        subprocess.run(controller + ['retire'], check=True)
        subprocess.run(controller + ['stage', version], check=True)
    else:
        if action in ('promote', 'rollback') and not version:
            raise ValueError('Version is required')
        subprocess.run(controller + [action] + ([version] if version else []), check=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # 不输出原始 JSON、Token 或 docker login 细节。
        print('Deployment command failed. Check release status and server logs.', file=sys.stderr)
        sys.exit(1)
