from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from sqlmodel import Session
from pydantic import BaseModel

from tricys_backend.utils.db import get_session
from tricys_backend.models.user import User
from tricys_backend.services.user_service import UserService
from tricys_backend.api.deps import get_current_user

router = APIRouter()

# Schema
class UserRead(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: bool = True
    is_superuser: bool = False

class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    
# Endpoints

@router.get("/me", response_model=UserRead)
def read_user_me(current_user: User = Depends(get_current_user)):
    """Get current user's profile."""
    return current_user

@router.patch("/me", response_model=UserRead)
def update_user_me(
    user_in: UserUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Update current user's profile."""
    updated = UserService.update_user(session, current_user.id, user_in.dict(exclude_unset=True))
    return updated

@router.get("/", response_model=List[UserRead])
def list_users(
    skip: int = 0, 
    limit: int = 100, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user) # Require auth to list users
):
    """List users (authenticated only)."""
    return UserService.list_users(session, skip, limit)

@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get user by ID (authenticated only)."""
    user = UserService.get_user(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
