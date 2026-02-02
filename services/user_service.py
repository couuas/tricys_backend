from typing import List, Optional
from sqlmodel import Session, select
from tricys_backend.models.user import User

class UserService:
    
    @staticmethod
    def get_user(session: Session, user_id: str) -> Optional[User]:
        return session.get(User, user_id)
        
    @staticmethod
    def get_user_by_username(session: Session, username: str) -> Optional[User]:
        statement = select(User).where(User.username == username)
        result = session.exec(statement)
        return result.first()
        
    @staticmethod
    def list_users(session: Session, skip: int = 0, limit: int = 100) -> List[User]:
        statement = select(User).offset(skip).limit(limit)
        return session.exec(statement).all()

    @staticmethod
    def update_user(session: Session, user_id: str, data: dict) -> Optional[User]:
        user = session.get(User, user_id)
        if not user: return None
        for key, value in data.items():
            if hasattr(user, key):
                setattr(user, key, value)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
