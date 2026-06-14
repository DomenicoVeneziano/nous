# backend/routers/auth_router.py
import math

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from schemas.user import LoginRequest, TokenResponse
from auth.jwt import create_jwt
from auth import rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)

    locked_for = rate_limit.check_allowed(ip)
    if locked_for > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(math.ceil(locked_for))},
        )

    user = db.query(User).filter(User.username == data.username).first()
    if not user or not user.verify_password(data.password):
        rate_limit.record_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    rate_limit.record_success(ip)
    token = create_jwt(user.id, user.role)
    return TokenResponse(access_token=token)
