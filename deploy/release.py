#!/usr/bin/env python3
"""单机发布控制器（兼容服务器 Python 3.6）：镜像部署、浏览器灰度、指定版本回滚。
所有变更串行执行；镜像 digest 和每版环境配置持久化，绝不自动降级数据库。
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time

VERSION = re.compile(r'^[a-z0-9][a-z0-9.-]{0,39}$')
IMAGE = re.compile(r'^ghcr\.io/git-king-bo/knowledge-base/(backend|frontend)@sha256:[a-f0-9]{64}$')
LOCAL_IMAGE = re.compile(r'^sha256:[a-f0-9]{64}$')


def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True, **kwargs).stdout.strip()


def pull_image(reference, timeout=1800, heartbeat=30):
    # Slow registry transfers must remain visible without printing credentials.
    print('Pulling image: ' + reference, flush=True)
    started = time.monotonic()
    process = subprocess.Popen(['docker', 'pull', reference], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, universal_newlines=True)
    try:
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise RuntimeError('Image download exceeded {} seconds; existing site was not switched. Retry after checking registry connectivity.'.format(timeout))
            try:
                output, errors = process.communicate(timeout=min(heartbeat, remaining))
                break
            except subprocess.TimeoutExpired:
                print('Image download still running: {} seconds elapsed (limit {} seconds).'.format(
                    int(time.monotonic() - started), timeout), flush=True)
        if process.returncode:
            # Registry errors can contain signed URLs. Do not echo raw output.
            raise RuntimeError('Image download failed; check Docker daemon logs and registry connectivity. Existing site was not switched.')
        print('Image downloaded in {} seconds.'.format(int(time.monotonic() - started)), flush=True)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.chmod(0o600)
    os.replace(str(temporary), str(path))


def acquire_release_lock(lock, action):
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        if action == 'status':
            return False
        raise RuntimeError('Another release operation is still running. Check status before retrying; no new deployment was started.')


def validate_manifest(value, local=False):
    if set(value) not in ({'version', 'commit', 'backend', 'frontend'},
                          {'version', 'commit', 'backend', 'frontend', 'image_ids'}):
        raise ValueError('Manifest requires version, commit, backend, frontend; image_ids is optional')
    if not VERSION.fullmatch(value['version']):
        raise ValueError('Invalid version')
    if not re.fullmatch(r'[a-f0-9]{40}', value['commit']):
        raise ValueError('A full commit SHA is required')
    for role in ('backend', 'frontend'):
        ref = value[role]
        match = IMAGE.fullmatch(ref)
        if not (match and match.group(1) == role) and not (local and LOCAL_IMAGE.fullmatch(ref)):
            raise ValueError('Image must use an approved repository and immutable digest')
    if 'image_ids' in value:
        ids = value['image_ids']
        if not isinstance(ids, dict) or set(ids) != {'backend', 'frontend'}:
            raise ValueError('Both offline image IDs are required')
        if any(not isinstance(i, str) or not LOCAL_IMAGE.fullmatch(i) for i in ids.values()):
            raise ValueError('Offline images must use immutable image IDs')
    return value


def image_reference(manifest, role):
    return manifest.get('image_ids', {}).get(role, manifest[role])


def docker_environment(source):
    """Convert our single-line, optionally shell-quoted snapshots to Docker syntax.

    No shell evaluation or variable expansion; never include values in errors.
    """
    result = []
    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise ValueError('Invalid environment assignment at line {}'.format(number))
        if value.startswith(('"', "'")):
            try:
                parts = shlex.split(value, comments=True, posix=True)
            except ValueError:
                raise ValueError('Invalid quoted environment value at line {}'.format(number)) from None
            if len(parts) != 1:
                raise ValueError('Expected one environment value at line {}'.format(number))
            value = parts[0]
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0].rstrip()
        if any(char in value for char in ('\n', '\r', '\0')):
            raise ValueError('Multiline environment values are not supported')
        result.append(key + '=' + value)
    return '\n'.join(result) + '\n'


class Releases:
    def __init__(self, root):
        self.root = root.resolve()
        self.directory = self.root / 'releases'
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.state_path = self.directory / 'state.json'
        self.journal = self.directory / 'pending.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            'active': None, 'previous': None, 'candidate': None, 'token': None}
        self.edge_file = self.root / 'deploy/Caddyfile.ecs'
        self.edge = 'knowledge-base-web-1'
        self.legacy_backend = 'knowledge-base-backend-1'
        self.network = 'knowledge-base_default'
        self.site = '120.27.205.41'

    def save(self):
        atomic_json(self.state_path, self.state)

    def manifest(self, version):
        if not VERSION.fullmatch(version):
            raise ValueError('Invalid version')
        return json.loads((self.directory / version / 'manifest.json').read_text())

    def register(self, path, local=False):
        value = validate_manifest(json.loads(Path(path).read_text()), local)
        directory = self.directory / value['version']
        if directory.exists():
            existing = self.manifest(value['version'])
            source = lambda item: {k: v for k, v in item.items() if k != 'image_ids'}
            if source(existing) != source(value):
                raise RuntimeError('Version already exists with different image digests')
            if 'image_ids' in existing and 'image_ids' in value and existing['image_ids'] != value['image_ids']:
                raise RuntimeError('Version already exists with different image IDs')
            return value['version']
        for role in ('backend', 'frontend'):
            ref = image_reference(value, role)
            if not LOCAL_IMAGE.fullmatch(ref):
                try:
                    run('docker', 'image', 'inspect', ref)
                    print('Using cached image: ' + ref, flush=True)
                except subprocess.CalledProcessError:
                    pull_image(ref)
            info = json.loads(run('docker', 'image', 'inspect', ref))[0]
            if info['Architecture'] != 'amd64' or info.get('Os', 'linux') != 'linux':
                raise RuntimeError('ECS requires linux/amd64 images')
        import tempfile
        draft = Path(tempfile.mkdtemp(prefix='.register-', dir=str(self.directory)))
        try:
            shutil.copyfile(str(self.root / 'deploy/production.env'), str(draft / 'runtime.env'))
            (draft / 'runtime.env').chmod(0o600)
            atomic_json(draft / 'manifest.json', value)
            # 完整写入后再出现版本目录；失败不留下半个版本。
            os.rename(str(draft), str(directory))
        finally:
            if draft.exists():
                shutil.rmtree(str(draft))
        return value['version']

    def name(self, role, version):
        return 'kb-{}-{}'.format(role, version)

    def inspect(self, name):
        try:
            return json.loads(run('docker', 'inspect', name))[0]
        except subprocess.CalledProcessError:
            return None

    def remove(self, name):
        if self.inspect(name):
            run('docker', 'stop', '--time', '300', name)
            run('docker', 'rm', name)

    def backend_args(self, version, worker=False):
        directory = self.directory / version
        # Keep the immutable source snapshot; Docker does not remove .env quotes.
        content = docker_environment((directory / 'runtime.env').read_text())
        target = directory / 'docker.env'
        temporary = directory / 'docker.env.tmp'
        with open(str(temporary), 'w', opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
            output.write(content)
        temporary.chmod(0o600)
        os.replace(str(temporary), str(target))
        return ['--env-file', str(target),
                '-e', 'APP_ENV=production', '-e', 'APP_AUTH_ENABLED=true',
                # 灰度共享一套 MySQL；禁止某个实例静默回退到独立 SQLite。
                '-e', 'APP_DATABASE_MODE=mysql', '-e', 'APP_MIGRATION_MODE=check',
                '-e', 'APP_WORKER_ENABLED=' + ('true' if worker else 'false'),
                '-v', str(self.root / 'data') + ':/data',
                '-v', str(self.root / 'data/storage') + ':/app/storage']

    def launch(self, role, version):
        name = self.name(role, version)
        existing = self.inspect(name)
        if existing:
            if not existing['State']['Running']:
                run('docker', 'start', name)
            return
        manifest = self.manifest(version)
        args = ['docker', 'run', '-d', '--name', name, '--network', self.network,
                '--restart', 'unless-stopped', '--stop-timeout', '300',
                '--log-driver', 'json-file', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3',
                '--label', 'kb.release=' + version, '--label', 'kb.role=' + role]
        if role in ('api', 'worker'):
            args += ['--memory', '640m'] + self.backend_args(version, worker=role == 'worker')
            args += ['--health-cmd', "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/ready',timeout=5)\"",
                     '--health-interval', '15s', '--health-timeout', '10s', '--health-start-period', '30s',
                     image_reference(manifest, 'backend')]
        else:
            args += ['--memory', '96m', '-e', 'API_UPSTREAM=' + self.name('api', version) + ':8001',
                     image_reference(manifest, 'frontend')]
        run(*args)

    def healthy(self, version, role='api'):
        self.wait_healthy(self.name(role, version))

    def wait_healthy(self, name):
        for attempt in range(40):
            info = self.inspect(name)
            if info and info['State'].get('Health', {}).get('Status') == 'healthy':
                return
            time.sleep(2)
        raise RuntimeError('Container not healthy: ' + name + '; inspect docker logs')

    def ensure(self, version):
        # 即使旧容器仍健康，也重新检查目标镜像与当前数据库是否匹配。
        # 这会拒绝跨 schema 版本回滚，并且不会自动 upgrade/downgrade。
        run(*(['docker', 'run', '--rm', '--network', self.network] + self.backend_args(version) +
              [image_reference(self.manifest(version), 'backend'), 'python', '-c',
               'from app.db.session import engine; from alembic.config import Config; '
               'from alembic.script import ScriptDirectory; '
               'from alembic.runtime.migration import MigrationContext; '
               'c=engine.connect(); expected=set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads()); '
               'actual=set(MigrationContext.configure(c).get_current_heads()); '
               'c.close(); assert actual == expected, "Database schema mismatch; release blocked"']))
        self.launch('api', version)
        self.healthy(version)
        self.launch('web', version)
        # 前端 HTTP 服务和 API 代理均须通过；测试不发送业务写请求。
        for attempt in range(20):
            try:
                run('docker', 'exec', self.name('web', version), 'wget', '-qO-', 'http://127.0.0.1:8080/ready')
                page = run('docker', 'exec', self.name('web', version), 'wget', '-qO-', 'http://127.0.0.1:8080/')
                if '<html' not in page.lower():
                    raise RuntimeError('Frontend is not HTML')
                return
            except subprocess.CalledProcessError:
                time.sleep(1)
        raise RuntimeError('Frontend readiness check failed')

    def config(self, active, candidate=None, token=None):
        def proxy(version):
            return ('        header X-KB-Release "' + version + '"\n'
                    '        reverse_proxy ' + self.name('web', version) + ':8080 {\n'
                    '            flush_interval -1\n        }\n')
        text = '''{
    default_sni SITE
}
SITE {
    tls {
        issuer acme https://acme-v02.api.letsencrypt.org/directory {
            profile shortlived
        }
    }
    encode zstd gzip
    header {
        X-Content-Type-Options nosniff
        Referrer-Policy same-origin
        X-Frame-Options DENY
    }
    handle /__release/stable {
        header Set-Cookie "kb_release=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict"
        header Cache-Control "no-store"
        redir / 302
    }
'''.replace('SITE', self.site)
        if candidate:
            if not token or not re.fullmatch('[a-f0-9]{48}', token):
                raise ValueError('Invalid preview token')
            text += ('    handle /__release/preview/' + token + ' {\n'
                     '        header Set-Cookie "kb_release=' + token + '; Path=/; Max-Age=86400; Secure; HttpOnly; SameSite=Strict"\n'
                     '        header Cache-Control "no-store"\n        redir / 302\n    }\n'
                     '    @preview header_regexp Cookie "(^|;[ ]*)kb_release=' + token + '(;|$)"\n'
                     '    handle @preview {\n' + proxy(candidate) + '    }\n')
        text += '    handle {\n' + proxy(active) + '    }\n}\n'
        return text

    def route(self, active, candidate=None, token=None):
        content = self.config(active, candidate, token)
        run('docker', 'exec', '-i', self.edge, 'caddy', 'validate', '--config', '-', '--adapter', 'caddyfile', input=content)
        old = self.edge_file.read_text()
        try:
            # 现有容器是单文件 bind mount，不能 os.replace（会让容器继续读取旧 inode）。
            self.edge_file.write_text(content)
            run('docker', 'exec', self.edge, 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile')
            self.verify_route(active, candidate, token)
        except Exception:
            self.edge_file.write_text(old)
            run('docker', 'exec', self.edge, 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile')
            raise

    def verify_route(self, active, candidate=None, token=None):
        for version, cookie in [(active, None)] + ([(candidate, token)] if candidate else []):
            args = ['curl', '--fail', '--silent', '--show-error', '--max-time', '15',
                    '--noproxy', '*', '--resolve', self.site + ':443:127.0.0.1', '-D', '-']
            if cookie:
                args += ['-H', 'Cookie: kb_release=' + cookie]
            result = run(*(args + ['https://' + self.site + '/ready']))
            if ('x-kb-release: ' + version).lower() not in result.lower():
                raise RuntimeError('Traffic did not reach expected release: ' + version)

    def backup(self):
        if self.state['active']:
            name = self.name('api', self.state['active'])
        else:
            name = self.legacy_backend
        stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S%fZ')
        directory = self.root / 'data/backups' / ('release-' + stamp)
        directory.mkdir(mode=0o700)
        os.chown(str(directory), 10001, 10001)
        run('docker', 'exec', '-e', 'APP_DATABASE_MODE=mysql', name, 'python', 'scripts/snapshot_mysql.py',
            '--output', '/data/backups/' + directory.name + '/knowledge_base.db')
        run('tar', '-czf', str(directory / 'uploads.tar.gz'), '-C', str(self.root / 'data'), 'storage/uploads')
        checksums = []
        for filename in ('knowledge_base.db', 'uploads.tar.gz'):
            digest = hashlib.sha256()
            with (directory / filename).open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
            checksums.append(digest.hexdigest() + '  ' + filename)
        (directory / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n')
        print('Backup completed:', directory)

    def stage(self, version):
        if not self.state['active']:
            raise RuntimeError('First run bootstrap with a verified baseline manifest')
        if version == self.state['active']:
            raise RuntimeError('Version is already active')
        if self.state['candidate'] and self.state['candidate'] != version:
            raise RuntimeError('Abort or promote the existing candidate first')
        self.retire()
        try:
            self.ensure(version)
        except Exception:
            if self.state['candidate'] != version:
                for role in ('web', 'api'):
                    self.remove(self.name(role, version))
            raise
        token = self.state['token'] or secrets.token_hex(24)
        atomic_json(self.journal, {'old': dict(self.state), 'target': version,
                                  'edge': self.edge_file.read_text()})
        try:
            self.route(self.state['active'], version, token)
            self.state.update(candidate=version, token=token)
            self.save()
        except Exception:
            self.recover()
            raise
        self.journal.unlink()
        print('Preview: https://' + self.site + '/__release/preview/' + token)

    def switch(self, version, bootstrap=False):
        old = dict(self.state)
        if old['active'] == version:
            raise RuntimeError('Version is already active')
        self.ensure(version)
        self.backup()
        if bootstrap:
            # 保存接管前配置作为人工应急回退材料，不删除旧容器或旧镜像。
            legacy = self.directory / 'legacy-Caddyfile'
            if not legacy.exists():
                legacy.write_text(self.edge_file.read_text())
        # 写前日志：进程/SSH 意外中断后，可用 recover 恢复切换前状态。
        atomic_json(self.journal, {'old': old, 'target': version, 'edge': self.edge_file.read_text()})
        old_worker = self.name('worker', old['active']) if old['active'] else self.legacy_backend
        try:
            if bootstrap:
                # 首次接管先把 HTTP 流量交给已健康的新 API，再停止带 worker 的旧后端。
                self.route(version)
            run('docker', 'stop', '--time', '300', old_worker)
            self.launch('worker', version)
            self.healthy(version, 'worker')
            self.route(version)
            self.state.update(active=version, previous=old['active'], candidate=None, token=None)
            self.save()
        except Exception:
            self.recover()
            raise
        self.journal.unlink()
        # 旧 API 和前端保留，供已经建立的流式请求结束；下一次发布前停止。
        print('Active release:', version)
        print('Old API containers can be drained with: release.py retire')

    def recover(self):
        pending = json.loads(self.journal.read_text())
        self.remove(self.name('worker', pending['target']))
        old = pending['old']
        if old['active']:
            self.launch('worker', old['active'])
            self.healthy(old['active'], 'worker')
        else:
            run('docker', 'start', self.legacy_backend)
            self.wait_healthy(self.legacy_backend)
        self.edge_file.write_text(pending['edge'])
        run('docker', 'exec', self.edge, 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile')
        self.state = old
        self.save()
        self.journal.unlink()
        print('Recovered the previous release')

    def abort(self):
        candidate = self.state['candidate']
        if not candidate:
            return
        self.route(self.state['active'])
        self.state.update(candidate=None, token=None)
        self.save()
        for role in ('web', 'api'):
            self.remove(self.name(role, candidate))

    def retire(self):
        # 保留镜像/版本清单/配置，只停止不再承载流量的容器。
        protected = {self.state['active'], self.state['candidate']}
        for path in self.directory.glob('*/manifest.json'):
            version = path.parent.name
            if version not in protected:
                for role in ('worker', 'web', 'api'):
                    self.remove(self.name(role, version))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/opt/knowledge-base'))
    parser.add_argument('action', choices=['register', 'bootstrap', 'stage', 'promote', 'rollback', 'abort', 'status', 'recover', 'retire', 'backup'])
    parser.add_argument('target', nargs='?')
    parser.add_argument('--local-images', action='store_true', help='Only for trusted administrator-imported offline images')
    args = parser.parse_args()
    deploy = Releases(args.root)
    with (deploy.directory / '.lock').open('a') as lock:
        locked = acquire_release_lock(lock, args.action)
        # 获取锁后重新读取状态，避免等锁期间状态已被另一个发布更新。
        deploy = Releases(args.root)
        if deploy.journal.exists() and args.action not in ('recover', 'status'):
            raise RuntimeError('Interrupted switch found; run recover before another operation')
        if args.action == 'register':
            print(deploy.register(args.target, args.local_images))
        elif args.action == 'bootstrap':
            if deploy.state['active']:
                raise RuntimeError('Already initialized')
            deploy.switch(deploy.register(args.target, args.local_images), bootstrap=True)
        elif args.action == 'stage':
            deploy.stage(args.target)
        elif args.action == 'promote':
            if args.target != deploy.state['candidate']:
                raise RuntimeError('Only the current candidate can be promoted')
            deploy.switch(args.target)
        elif args.action == 'rollback':
            if deploy.state['candidate']:
                raise RuntimeError('Abort candidate before rollback')
            deploy.manifest(args.target)
            deploy.switch(args.target)
        elif args.action == 'status':
            public = {k: v for k, v in deploy.state.items() if k != 'token'}
            public['versions'] = sorted(p.parent.name for p in deploy.directory.glob('*/manifest.json'))
            public['recovery_required'] = deploy.journal.exists()
            public['operation_in_progress'] = not locked
            print(json.dumps(public, indent=2))
        else:
            getattr(deploy, args.action)()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        # 不回显 docker 参数或环境文件，避免泄漏配置中的凭据。
        print('Release failed: ' + (str(exc) if not isinstance(exc, subprocess.CalledProcessError)
                                  else 'Command failed; inspect container/service logs'), file=sys.stderr)
        sys.exit(1)
