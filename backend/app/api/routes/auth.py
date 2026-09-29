import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import UserModel, LoginSessionModel, BaseAccessModel
from app.core.config import settings
from app.core.security import (authenticate, require_admin, rate_limit, now,
    password_hash, verify_password, audit)

router = APIRouter()

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)

class NewUser(Login):
    role: str = 'viewer'

class PasswordChange(BaseModel):
    old_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


def public(user):
    return {'id': user.id, 'username': user.username, 'role': user.role, 'enabled': user.enabled}

@router.post('/login')
def login(payload: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    rate_limit('login:' + (request.client.host if request.client else 'unknown'), 10)
    user = db.scalar(select(UserModel).where(UserModel.username == payload.username))
    if not user or not user.enabled or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, '用户名或密码错误')
    token = secrets.token_urlsafe(40)
    db.add(LoginSessionModel(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                            expires_at=now()+timedelta(hours=settings.session_hours)))
    db.commit()
    response.set_cookie('kb_session', token, httponly=True, samesite='strict',
                        secure=settings.app_env=='production', max_age=settings.session_hours*3600, path='/api')
    return public(user)

@router.get('/me')
def me(user=Depends(authenticate)):
    return public(user) if user else {'id':'local','username':'local','role':'admin','enabled':True}

@router.post('/logout')
def logout(request: Request, response: Response, user=Depends(authenticate), db: Session = Depends(get_db)):
    token = request.cookies.get('kb_session', '')
    db.execute(delete(LoginSessionModel).where(LoginSessionModel.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    db.commit()
    response.delete_cookie('kb_session', path='/api')
    return {'ok': True}

@router.post('/password')
def change_password(payload: PasswordChange, user=Depends(authenticate), db: Session = Depends(get_db)):
    if not user or not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(400, '原密码错误')
    user.password_hash = password_hash(payload.new_password)
    db.execute(delete(LoginSessionModel).where(LoginSessionModel.user_id == user.id))
    db.commit()
    audit(db, 'password.changed', user.id)
    return {'ok': True}

@router.get('/users')
def users(user=Depends(authenticate), db: Session = Depends(get_db)):
    require_admin()
    return [public(u) for u in db.scalars(select(UserModel))]

@router.post('/users')
def create_user(payload: NewUser, user=Depends(authenticate), db: Session = Depends(get_db)):
    require_admin()
    if payload.role not in {'admin','editor','viewer'} or len(payload.password)<12:
        raise HTTPException(400,'角色无效或密码少于12位')
    if db.scalar(select(UserModel.id).where(UserModel.username==payload.username)):
        raise HTTPException(409,'用户名已存在')
    item=UserModel(id=str(uuid4()), username=payload.username, password_hash=password_hash(payload.password),
                   role=payload.role, enabled=True, created_at=now())
    db.add(item);db.commit();audit(db,'user.created',item.id)
    return public(item)

@router.put('/users/{user_id}/enabled')
def enable_user(user_id: str, enabled: bool, user=Depends(authenticate), db: Session = Depends(get_db)):
    require_admin()
    item=db.get(UserModel,user_id)
    if not item: raise HTTPException(404,'用户不存在')
    if user and user.id==user_id: raise HTTPException(400,'不能停用当前账号')
    item.enabled=enabled
    db.execute(delete(LoginSessionModel).where(LoginSessionModel.user_id==user_id))
    db.commit();audit(db,'user.enabled',user_id,str(enabled))
    return public(item)

@router.get('/access/{base_id}')
def list_access(base_id: str, user=Depends(authenticate), db: Session=Depends(get_db)):
    require_admin()
    return [{'user_id':x.user_id,'role':x.role} for x in db.scalars(select(BaseAccessModel).where(BaseAccessModel.base_id==base_id))]

@router.put('/access/{base_id}/{user_id}')
def grant(base_id: str,user_id: str,role: str, user=Depends(authenticate),db: Session=Depends(get_db)):
    from app.db.models import KnowledgeBaseModel
    require_admin()
    if role not in {'viewer','editor','none'}: raise HTTPException(400,'无效角色')
    if not db.get(KnowledgeBaseModel,base_id) or not db.get(UserModel,user_id): raise HTTPException(404,'用户或知识库不存在')
    entry=db.get(BaseAccessModel,(base_id,user_id))
    if entry: db.delete(entry);db.flush()
    if role!='none': db.add(BaseAccessModel(base_id=base_id,user_id=user_id,role=role))
    db.commit();audit(db,'access.changed',base_id,f'{user_id}:{role}')
    return {'ok':True}
