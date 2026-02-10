from fastapi import Request, HTTPException, Depends
from typing import Optional
from tricys_backend.core.security import decode_access_token
from tricys_backend.utils.db import get_session
from tricys_backend.models.user import User
from sqlmodel import Session
from tricys_backend.api.token_utils import extract_token

ALLOW_LIST = {
    ("GET", "/project/getData"),
    ("GET", "/sys/getOssInfo"),
    ("POST", "/sys/login"),
}

def is_allowed(method: str, path: str) -> bool:
    return (method.upper(), path) in ALLOW_LIST

def require_token(request: Request, session: Session = Depends(get_session)) -> User:
    path = request.url.path.replace("/api/v2/goview", "")
    if is_allowed(request.method, path):
        return None

    token = extract_token(request)
    if not token:
        # 886 is specific code for GoView to redirect to login
        raise HTTPException(status_code=200, detail="token overdue")
    
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=200, detail="token overdue")
            
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=200, detail="token overdue")
        return user
    except Exception:
        raise HTTPException(status_code=200, detail="token overdue")

def optional_token(request: Request, session: Session = Depends(get_session)) -> Optional[User]:
    token = extract_token(request)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        return session.get(User, payload.get("sub"))
    except Exception:
        return None
