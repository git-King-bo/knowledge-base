"""Authentication, envelope encryption and scoped access for a single team."""
import base64
from collections import defaultdict, deque
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import os
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db

actor = ContextVar('actor', default=None)
usage_counter = ContextVar('usage_counter', default=None)
_rate_lock = threading.Lock()
_rates = defaultdict(deque)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def private_file(name, factory):
    root = Path(settings.security_dir)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / name
    if not path.exists():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as file:
                file.write(factory())
        except FileExistsError:
            pass
    return path.read_text().strip()


def cipher():
    key = settings.encryption_key or private_file('encryption.key', lambda: Fernet.generate_key().decode())
    return Fernet(key.encode())


def encrypt_secret(value):
    return 'fernet:' + cipher().encrypt(value.encode()).decode() if value else ''


def decrypt_secret(value):
    if not value:
        return None
    if not value.startswith('fernet:'):
        # Legacy plaintext is migrated on startup; never expose it through APIs.
        return value
    return cipher().decrypt(value[7:].encode()).decode()


def password_hash(value):
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(value.encode(), salt=salt, n=16384, r=8, p=1)
    return f'scrypt${salt.hex()}${derived.hex()}'


def verify_password(value, stored):
    try:
        _, salt, expected = stored.split('$')
        actual = hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def rate_limit(key, limit):
    with _rate_lock:
        current = time.monotonic()
        if len(_rates) > 10000:
            for old in list(_rates):
                if not _rates[old] or _rates[old][-1] < current - 60:
                    del _rates[old]
        queue = _rates[key]
        while queue and queue[0] < current - 60:
            queue.popleft()
        if len(queue) >= limit:
            raise HTTPException(429, '请求过于频繁，请稍后重试', headers={'Retry-After': '60'})
        queue.append(current)


def validate_provider_url(value, *, resolve=False):
    url = urlsplit(value)
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise HTTPException(400, '模型地址必须是有效的 HTTP(S) 地址，不能包含凭据或查询参数')
    host = url.hostname.lower()
    allowed = {x.strip().lower() for x in settings.provider_allowed_hosts.split(',') if x.strip()}
    if settings.app_env == 'production' and not allowed:
        raise HTTPException(503, '生产环境必须配置模型服务域名白名单')
    if allowed and host not in allowed:
        raise HTTPException(400, '模型域名不在允许列表中')
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = []
        if resolve:
            try:
                addresses = [ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(host, url.port or 443)]
            except OSError:
                raise HTTPException(502, '无法解析模型服务域名')
    if not settings.allow_private_providers and (host == 'localhost' or any(not x.is_global for x in addresses)):
        raise HTTPException(400, '不允许连接本机、内网或保留地址')
    if settings.app_env == 'production' and url.scheme != 'https':
        raise HTTPException(400, '生产模型服务必须使用 HTTPS')
    return value


def audit(db, action, target, detail=''):
    from app.db.models import AuditModel
    user = actor.get()
    db.add(AuditModel(id=str(uuid4()), user_id=user.id if user else None,
                     action=action, target=target, detail=detail, created_at=now()))
    db.commit()


def initialize_security(db):
    from app.db.models import UserModel, AIProviderModel
    cipher()  # Validate and persist the installation key before accepting requests.
    if settings.auth_enabled and not db.scalar(select(UserModel.id).limit(1)):
        password = private_file('initial-admin-password.txt', lambda: secrets.token_urlsafe(24))
        db.add(UserModel(id=str(uuid4()), username='admin', password_hash=password_hash(password),
                         role='admin', enabled=True, created_at=now()))
    for provider in db.scalars(select(AIProviderModel)):
        if provider.api_key_encrypted and not provider.api_key_encrypted.startswith('fernet:'):
            provider.api_key_encrypted = encrypt_secret(provider.api_key_encrypted)
        elif provider.api_key_encrypted:
            decrypt_secret(provider.api_key_encrypted)
    db.commit()


def allowed_base_ids(db, user=None, write=False):
    from app.db.models import BaseAccessModel
    user = user or actor.get()
    if not user or user.role == 'admin':
        return None
    query = select(BaseAccessModel.base_id).where(BaseAccessModel.user_id == user.id)
    if write:
        query = query.where(BaseAccessModel.role == 'editor')
    return list(db.scalars(query))


def check_base(db, base_id, write=False):
    ids = allowed_base_ids(db, write=write)
    if ids is not None and base_id not in ids:
        raise HTTPException(404, '知识库不存在或没有访问权限')


def check_source(db, source_id, write=False):
    from app.db.models import KnowledgeBaseSourceModel
    ids = allowed_base_ids(db, write=write)
    if ids is not None and not db.scalar(select(KnowledgeBaseSourceModel.id).where(
            KnowledgeBaseSourceModel.source_id == source_id, KnowledgeBaseSourceModel.knowledge_base_id.in_(ids))):
        raise HTTPException(404, '资料不存在或没有访问权限')


def require_admin():
    user = actor.get()
    if settings.auth_enabled and (not user or user.role != 'admin'):
        raise HTTPException(403, '需要管理员权限')


async def authenticate(request: Request, db: Session = Depends(get_db)):
    from app.db.models import LoginSessionModel, UserModel
    if not settings.auth_enabled:
        if settings.app_env == 'production':
            raise HTTPException(503, '生产环境不可关闭鉴权')
        yield None
        return
    token = request.headers.get('Authorization', '').removeprefix('Bearer ') or request.cookies.get('kb_session', '')
    session = db.get(LoginSessionModel, hashlib.sha256(token.encode()).hexdigest()) if token else None
    user = db.get(UserModel, session.user_id) if session and session.expires_at > now() else None
    if not user or not user.enabled:
        raise HTTPException(401, '请先登录')
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not request.headers.get('Authorization'):
        if request.headers.get('X-Requested-With') != 'knowledge-base':
            raise HTTPException(403, '缺少请求验证头')
        origin = request.headers.get('origin')
        if origin and origin not in settings.cors_origins and origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '请求来源不受信任')
    rate_limit('user:'+user.id, settings.requests_per_minute)
    token_context = actor.set(user)
    db.info['actor'] = (user.id, user.role)
    try:
        yield user
    finally:
        db.info.pop('actor', None)
        actor.reset(token_context)


async def authorize(request: Request, db: Session = Depends(get_db), user=Depends(authenticate)):
    if not user:
        yield
        return
    path = request.url.path
    write = request.method not in {'GET', 'HEAD', 'OPTIONS'}
    inference = path.endswith(('/ask', '/ask/stream', '/chat', '/search'))
    if path.startswith('/api/ai/') and (write and not path.endswith('/chat') or path.endswith('/logs')):
        require_admin()
    if path.startswith('/api/usage'):
        require_admin()
    if write and not inference and user.role == 'viewer' and not path.startswith('/api/conversations'):
        raise HTTPException(403, '只读账号不能修改资料')
    base_id = request.path_params.get('knowledge_base_id') or request.query_params.get('knowledge_base_id')
    if inference and request.method == 'POST':
        payload = await request.json()
        base_id = payload.get('knowledge_base_id')
    if base_id:
        check_base(db, base_id, write=write and not inference)
    source_id = request.path_params.get('source_id')
    if source_id:
        check_source(db, source_id, write=write)
    if user.role != 'admin' and path == '/api/knowledge/upload':
        raise HTTPException(403, '请选择有权限的知识库上传')

    yield
    if write:
        audit(db, request.method.lower(), path)
