from typing import Any, Dict

class ResultCode:
    SUCCESS = 200
    TOKEN_OVERDUE = 886
    SERVER_ERROR = 500
    FAIL = 400

def success(data: Any = None, msg: str = "success") -> Dict[str, Any]:
    return {"code": ResultCode.SUCCESS, "msg": msg, "data": data}

def error(code: int, msg: str) -> Dict[str, Any]:
    return {"code": code, "msg": msg, "data": None}
