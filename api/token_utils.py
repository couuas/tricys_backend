from typing import Optional
from fastapi import Request


def extract_token(request: Request) -> Optional[str]:
    # 1. Try header "token" (GoView standard)
    token = request.headers.get("token")
    if token:
        return token

    # 2. Try Authorization: Bearer <token>
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth.replace("Bearer ", "", 1)

    # 3. Try query param "token"
    token = request.query_params.get("token")
    if token:
        return token

    return None
