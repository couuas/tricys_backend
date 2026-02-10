from fastapi import APIRouter, Depends, Request, Form
from sqlmodel import Session, select
from typing import Any, Optional

from tricys_backend.utils.db import get_session
from tricys_backend.core.security import verify_password, create_access_token
from tricys_backend.models.user import User
from tricys_backend.api.v2.goview.responses import success, error

router = APIRouter()

@router.post("/login")
async def login(
    request: Request,
    session: Session = Depends(get_session)
) -> Any:
    """
    GoView-compatible login endpoint.
    Accepts both JSON body and Form data.
    """
    payload = {}
    content_type = request.headers.get("content-type", "")
    username = None
    password = None

    if "application/json" in content_type:
        try:
            payload = await request.json()
            username = payload.get("username")
            password = payload.get("password")
        except Exception:
            pass
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        try:
            form = await request.form()
            username = form.get("username")
            password = form.get("password")
        except Exception:
            pass
    
    # Fallback to query params if still None? (GoView unlikely uses query)
    if not username or not password:
         return error(400, "username and password required")

    user = session.exec(select(User).where(User.username == username)).first()
    if not user or not verify_password(password, user.hashed_password):
        return error(400, "invalid username or password")
    
    if not user.is_active:
        return error(400, "user inactive")

    token = create_access_token(user.id)
    return success({
        "token": {"tokenValue": token, "tokenName": "token"},
        "userinfo": {
            "nickname": user.full_name or user.username,
            "username": user.username,
            "id": user.id
        }
    })

@router.get("/logout")
def logout():
    return success(None)

@router.get("/getOssInfo")
def get_oss_info():
    # Return upload endpoint for GoView
    return success({"bucketURL": "/api/v2/goview/project/upload"})
