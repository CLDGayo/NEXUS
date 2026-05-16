"""Authentication — password login returning a JWT."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel

from auth_overlay import current_jwt_secret, verify_password

router = APIRouter(tags=["auth"])

JWT_EXPIRY_DAYS = 7


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")

    expires = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS)
    token = jwt.encode(
        {"sub": "admin", "exp": expires},
        current_jwt_secret(),
        algorithm="HS256",
    )
    return LoginResponse(token=token, expires_at=expires.isoformat())
