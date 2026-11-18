import base64, hashlib, hmac, secrets
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config import settings
from .db import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)
def hash_password(password):
    salt=secrets.token_bytes(16)
    digest=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1)
    return base64.b64encode(salt+digest).decode()
def check_password(password, encoded):
    try:
        raw=base64.b64decode(encoded)
        return hmac.compare_digest(raw[16:],hashlib.scrypt(password.encode(),salt=raw[:16],n=16384,r=8,p=1))
    except (ValueError,TypeError): return False
def token_for(user):
    return jwt.encode({'sub':user.id,'exp':datetime.now(timezone.utc)+timedelta(hours=8)},settings.jwt_secret,algorithm='HS256')
def current_user(credentials:HTTPAuthorizationCredentials|None=Depends(bearer),db=Depends(get_db)):
    if not credentials: raise HTTPException(401,'Vui lòng đăng nhập.')
    try:
        payload=jwt.decode(credentials.credentials,settings.jwt_secret,algorithms=['HS256'])
        user=db.get(User,payload['sub'])
    except (jwt.PyJWTError,KeyError): raise HTTPException(401,'Phiên đăng nhập hết hạn.')
    if not user or not user.active: raise HTTPException(401,'Tài khoản không hoạt động.')
    return user
def admin(user=Depends(current_user)):
    if user.role!='admin': raise HTTPException(403,'Chức năng dành cho quản trị viên.')
    return user
def allowed_source(source,user):
    return source.enabled and (user.role=='admin' or source.access_scope=='PUBLIC' or user.role in source.allowed_roles)
def allowed_document(document,source,user):
    return allowed_source(source,user) and (user.role=='admin' or document.access_scope in ['PUBLIC','INHERIT'] or user.role in document.allowed_roles)
