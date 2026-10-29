import jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import settings

security = HTTPBearer()


def get_jwt_secret() -> str:
    secret = settings.JWT_SECRET
    if len(secret.encode("utf-8")) < settings.JWT_SECRET_MIN_BYTES:
        raise RuntimeError(
            f"JWT_SECRET must be set to a random value of at least {settings.JWT_SECRET_MIN_BYTES} bytes"
        )
    return secret


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        return jwt.decode(
            credentials.credentials,
            get_jwt_secret(),
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp"]},
        )
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
