from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import Depends, HTTPException, Request
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


@dataclass
class GoviewTokenContext:
    user: Optional[User]
    token_payload: Dict
    operator_user_id: Optional[str]
    tricys_project_id: Optional[str]
    scope: str

    @property
    def is_project_scoped(self) -> bool:
        return bool(self.tricys_project_id)


def _decode_request_payload(request: Request) -> Dict:
    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=200, detail="token overdue")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=200, detail="token overdue")
    return payload


def _build_context(session: Session, payload: Dict) -> GoviewTokenContext:
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=200, detail="token overdue")

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=200, detail="token overdue")

    return GoviewTokenContext(
        user=user,
        token_payload=payload,
        operator_user_id=payload.get("operator_user_id") or user_id,
        tricys_project_id=payload.get("tricys_project_id") or payload.get("project_id"),
        scope=str(payload.get("scope") or "goview:user"),
    )


def require_goview_context(request: Request, session: Session = Depends(get_session)) -> GoviewTokenContext:
    path = request.url.path.replace("/api/v2/goview", "")
    if is_allowed(request.method, path):
        return GoviewTokenContext(
            user=None,
            token_payload={},
            operator_user_id=None,
            tricys_project_id=None,
            scope="goview:anonymous",
        )

    payload = _decode_request_payload(request)
    return _build_context(session, payload)


def optional_goview_context(request: Request, session: Session = Depends(get_session)) -> Optional[GoviewTokenContext]:
    token = extract_token(request)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    try:
        return _build_context(session, payload)
    except HTTPException:
        return None

def require_token(request: Request, session: Session = Depends(get_session)) -> User:
    return require_goview_context(request, session).user

def optional_token(request: Request, session: Session = Depends(get_session)) -> Optional[User]:
    context = optional_goview_context(request, session)
    return context.user if context else None
