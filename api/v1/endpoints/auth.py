from datetime import timedelta
from typing import Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session

from tricys_backend.utils.db import get_session
from tricys_backend.core.security import create_access_token, get_password_hash, verify_password
from tricys_backend.models.user import User
from tricys_backend.core.config import settings

router = APIRouter()

@router.post("/login")
def login_access_token(
    session: Session = Depends(get_session), 
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    # Find user
    from sqlmodel import select
    user = session.exec(select(User).where(User.username == form_data.username)).first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
        
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }

class UserRegister(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    email: Optional[str] = None

@router.post("/register")
def register_user(
    user_in: UserRegister,
    session: Session = Depends(get_session)
) -> Any:
    """
    Create new user without the need for admin privileges (for local setup)
    """
    from sqlmodel import select
    user = session.exec(select(User).where(User.username == user_in.username)).first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system",
        )
    
    from sqlmodel import func
    user_count = session.exec(select(func.count()).select_from(User)).one()

    user = User(
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        email=user_in.email,
        is_superuser=(user_count == 0) # Promote first user to admin
    )
    session.add(user)
    session.commit()
    return {"status": "success", "msg": "User created successfully"}
