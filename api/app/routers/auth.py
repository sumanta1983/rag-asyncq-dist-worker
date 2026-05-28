import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import get_current_user
from ..auth.security import (
    MOBILE_REGEX,
    create_access_token,
    hash_password,
    normalize_mobile,
    verify_password,
)
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    mobile: str
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @field_validator("mobile")
    @classmethod
    def _check_mobile(cls, v: str) -> str:
        canonical = normalize_mobile(v)
        digits = canonical[3:]  # drop +91
        if not re.match(MOBILE_REGEX, digits):
            raise ValueError("mobile must be a 10-digit Indian number starting with 6-9")
        return canonical


class LoginRequest(BaseModel):
    mobile: str
    password: str

    @field_validator("mobile")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_mobile(v)


class UserOut(BaseModel):
    id: int
    name: str
    mobile: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if req.password != req.confirm_password:
        raise HTTPException(status_code=400, detail="passwords do not match")

    exists = db.scalar(select(User).where(User.mobile == req.mobile))
    if exists:
        raise HTTPException(status_code=409, detail="mobile already registered")

    user = User(
        name=req.name.strip(),
        mobile=req.mobile,
        password_hash=hash_password(req.password),
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return TokenResponse(
        access_token=create_access_token(user_id=user.id, role=user.role),
        user=UserOut(id=user.id, name=user.name, mobile=user.mobile, role=user.role),
    )


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.mobile == req.mobile))
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")

    return TokenResponse(
        access_token=create_access_token(user_id=user.id, role=user.role),
        user=UserOut(id=user.id, name=user.name, mobile=user.mobile, role=user.role),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, name=user.name, mobile=user.mobile, role=user.role)
