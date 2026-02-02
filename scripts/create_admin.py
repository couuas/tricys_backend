import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from sqlmodel import Session, select
from tricys_backend.utils.db import engine
from tricys_backend.models.user import User
from tricys_backend.core.security import get_password_hash

def create_admin(username, password, full_name="System Admin"):
    with Session(engine) as session:
        # Check if exists
        existing = session.exec(select(User).where(User.username == username)).first()
        if existing:
            print(f"User {username} already exists. Updating to superuser...")
            existing.is_superuser = True
            existing.is_active = True
            session.add(existing)
            session.commit()
            print("Done.")
            return

        new_user = User(
            username=username,
            hashed_password=get_password_hash(password),
            full_name=full_name,
            is_superuser=True,
            is_active=True
        )
        session.add(new_user)
        session.commit()
        print(f"Admin user '{username}' created successfully!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Create TRICYS Admin")
    parser.add_argument("--user", default="admin", help="Admin username")
    parser.add_argument("--pwd", default="admin123", help="Admin password")
    args = parser.parse_args()
    
    create_admin(args.user, args.pwd)
