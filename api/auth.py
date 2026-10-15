import os
import jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

MIN_JWT_SECRET_BYTES = 32


def get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if len(secret.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
        raise RuntimeError(
            f"JWT_SECRET must be set to a random value of at least {MIN_JWT_SECRET_BYTES} bytes"
        )
    return secret


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token, get_jwt_secret(), algorithms=["HS256"], options={"require": ["exp"]}
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(payload: dict = Depends(verify_token)) -> dict:
    uid = payload.get("uid")
    if uid is None:
        raise HTTPException(status_code=401, detail="Token missing uid")
    return payload


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("is_admin") is not True:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return user
