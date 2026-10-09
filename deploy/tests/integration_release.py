"""手动 Docker 集成演练。只使用随机命名的本机容器与空白测试库，不访问线上。
先构建 knowledge-base-release-test:{backend,frontend}，并准备 mysql:8.4。
运行：backend/.venv/bin/python deploy/tests/integration_release.py
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request

spec=importlib.util.spec_from_file_location('release',Path(__file__).resolve().parents[1]/'release.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class LocalRelease(r.Releases):
    def config(self,*args):
        original=super().config(*args)
        # 本机回环 HTTP 验证路由；生产 TLS 配置另外用 Caddy validate 验证。
        original=original.replace('{\n    default_sni '+self.site+'\n}\n','',1)
        original=original.replace(self.site+' {',':8080 {',1)
        original=re.sub(r'    tls \{\n.*?\n    \}\n','',original,count=1,flags=re.S)
        return original

    def request(self,token=None,path='/ready'):
        request=urllib.request.Request('http://127.0.0.1:'+self.port+path)
        if token:request.add_header('Cookie','kb_release='+token)
        return urllib.request.urlopen(request,timeout=15)

    def verify_route(self,active,candidate=None,token=None):
        with self.request() as response:assert response.headers['X-KB-Release']==active
        if candidate:
            with self.request(token) as response:assert response.headers['X-KB-Release']==candidate

    def backup(self):
        # 仍然执行真实的一致性导出，仅避免 macOS 宿主上的 root chown 操作。
        output='/data/backups/test-'+secrets.token_hex(4)+'.db'
        name=self.name('api',self.state['active']) if self.state['active'] else self.legacy_backend
        r.run('docker','exec',name,'python',
              'scripts/snapshot_mysql.py','--output',output)


def main():
    suffix=secrets.token_hex(4);db_name='kb-test-db-'+suffix;edge='kb-test-edge-'+suffix
    network='kb-test-net-'+suffix;password=secrets.token_hex(16)
    old='test-old-'+suffix;new='test-new-'+suffix
    legacy='kb-test-legacy-'+suffix
    containers=[db_name,edge,legacy]+['kb-'+role+'-'+version for version in (old,new) for role in ('api','web','worker')]
    with tempfile.TemporaryDirectory(prefix='kb-release-test-') as temporary:
        root=Path(temporary)
        for path in ['deploy','data','data/backups','data/storage','data/storage/uploads','data/storage/security']:
            target=root/path;target.mkdir(parents=True,exist_ok=True);target.chmod(0o777)
        (root/'deploy/production.env').write_text('\n'.join([
            'XINIU_MYSQL_HOST='+db_name,'XINIU_MYSQL_PORT=3306','XINIU_MYSQL_DATABASE=release_test',
            'XINIU_MYSQL_USER=root','XINIU_MYSQL_PASSWORD='+password,
            'APP_SECURITY_DIR=storage/security','APP_UPLOAD_DIR=storage/uploads',
            'AGENT_DEFAULT_API_URL=','AGENT_EMBEDDING_API_URL=']))
        (root/'deploy/Caddyfile.ecs').write_text(':8080 {\n respond "boot"\n}\n')
        deploy=LocalRelease(root);deploy.network=network;deploy.edge=edge;deploy.legacy_backend=legacy
        try:
            r.run('docker','network','create',network)
            r.run('docker','run','-d','--name',db_name,'--network',network,
                  '-e','MYSQL_ROOT_PASSWORD='+password,'-e','MYSQL_ROOT_HOST=%',
                  '-e','MYSQL_DATABASE=release_test','mysql:8.4')
            for attempt in range(90):
                try:
                    r.run('docker','exec','-e','MYSQL_PWD='+password,db_name,'mysql','-uroot','-e','SELECT 1')
                    break
                except subprocess.CalledProcessError:time.sleep(2)
            else:raise RuntimeError('MySQL did not start')
            images={role:json.loads(r.run('docker','image','inspect','knowledge-base-release-test:'+role))[0]['Id']
                    for role in ('backend','frontend')}
            for version in (old,new):
                manifest=root/(version+'.json')
                manifest.write_text(json.dumps(dict(version=version,commit='a'*40,**images)))
                deploy.register(str(manifest),local=True)
            r.run(*(['docker','run','--rm','--network',network]+deploy.backend_args(old)+
                    ['-e','APP_MIGRATION_MODE=upgrade',images['backend'],'python','-c',
                     'from app.db.init_db import init_db; init_db()']))
            r.run(*(['docker','run','-d','--name',legacy,'--network',network]+deploy.backend_args(old,worker=True)+[
                '--health-cmd',"python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/ready')\"",
                '--health-interval','2s',images['backend']]))
            deploy.wait_healthy(legacy)
            r.run('docker','run','-d','--name',edge,'--network',network,
                  '-p','127.0.0.1::8080','-v',str(root/'deploy/Caddyfile.ecs')+':/etc/caddy/Caddyfile',images['frontend'])
            info=json.loads(r.run('docker','inspect',edge))[0]
            deploy.port=info['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort']
            for attempt in range(20):
                try:
                    r.run('docker','exec',edge,'caddy','validate','--config','/etc/caddy/Caddyfile');break
                except subprocess.CalledProcessError:time.sleep(1)
            # 生产格式也能被同一 Caddy 镜像解析和校验。
            r.run('docker','exec','-i',edge,'caddy','validate','--config','-','--adapter','caddyfile',
                  input=r.Releases.config(deploy,old,new,'a'*48))
            deploy.switch(old,bootstrap=True)
            assert not deploy.inspect(legacy)['State']['Running']
            print('PASS: bootstrap moves traffic before stopping legacy backend; new singleton worker healthy')
            deploy.stage(new)
            assert deploy.inspect(deploy.name('worker',new)) is None
            deploy.verify_route(old,new,deploy.state['token'])
            with deploy.request(deploy.state['token'],'/') as response:assert b'<html' in response.read()
            print('PASS: stable and preview frontend/API route to different releases; only one worker')
            deploy.switch(new)
            assert not deploy.inspect(deploy.name('worker',old))['State']['Running']
            assert deploy.inspect(deploy.name('worker',new))['State']['Running']
            r.run('docker','exec','-e','MYSQL_PWD='+password,db_name,'mysql','-uroot','release_test','-e',
                  'CREATE TABLE release_test_marker (id INTEGER); INSERT INTO release_test_marker VALUES (42)')
            deploy.switch(old)
            count=r.run('docker','exec','-e','MYSQL_PWD='+password,db_name,'mysql','-uroot','release_test','-Nse',
                        'SELECT id FROM release_test_marker')
            assert count=='42';deploy.verify_route(old)
            print('PASS: promote, exact-version rollback and database writes preserved')
            deploy.stage(new);deploy.abort();deploy.verify_route(old)
            assert deploy.inspect(deploy.name('api',new)) is None
            print('PASS: abort removes candidate only')
            r.run('docker','exec','-e','MYSQL_PWD='+password,db_name,'mysql','-uroot','release_test','-e',
                  "UPDATE alembic_version SET version_num='future_schema'")
            try:deploy.stage(new)
            except subprocess.CalledProcessError:pass
            else:raise AssertionError('Schema mismatch should block candidate startup')
            assert deploy.state['active']==old
            print('PASS: incompatible schema blocked without switching stable traffic')
        finally:
            for container in containers:
                subprocess.run(['docker','rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            subprocess.run(['docker','network','rm',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':main()
