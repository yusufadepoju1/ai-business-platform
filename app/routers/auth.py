from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import admin_user, current_business, current_user, get_owned
from ..models import Business, User
from ..ratelimit import rate_limit
from ..security import (create_access_token, hash_password, new_public_key, new_webhook_secret, verify_password)
from ..services.conversation import ensure_agents

router = APIRouter(prefix="/api", tags=["auth"])


class RegisterIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=200)
    industry: str = Field(default="general", max_length=100)
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


def user_out(u: User, b: Business | None = None) -> dict:
    d = {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
         "business_id": u.business_id}
    if b:
        d["business_name"] = b.name
        d["is_demo"] = b.is_demo
    return d


@router.post("/auth/register", status_code=201, dependencies=[Depends(rate_limit("register", 10, 3600))])
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none():
        raise HTTPException(409, "An account with this email already exists.")
    biz = Business(name=body.business_name.strip(), industry=body.industry.strip() or "general", email=email,
                   notification_email=email, public_key=new_public_key(), webhook_secret=new_webhook_secret())
    db.add(biz)
    db.flush()
    user = User(business_id=biz.id, email=email, full_name=body.full_name.strip(),
                hashed_password=hash_password(body.password), role="owner")
    db.add(user)
    db.commit()
    ensure_agents(db, biz.id)
    return {"access_token": create_access_token(user.id, biz.id, user.role), "token_type": "bearer", "user": user_out(user, biz)}


@router.post("/auth/login", dependencies=[Depends(rate_limit("login", 20, 60))])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(func.lower(User.email) == body.email.lower())).scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password) or not user.is_active:
        raise HTTPException(401, "Incorrect email or password.")
    biz = db.get(Business, user.business_id)
    return {"access_token": create_access_token(user.id, biz.id, user.role), "token_type": "bearer", "user": user_out(user, biz)}


@router.get("/auth/me")
def me(user: User = Depends(current_user), biz: Business = Depends(current_business)):
    return user_out(user, biz)


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)


@router.put("/auth/me")
def update_me(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.full_name = body.full_name.strip()
    db.commit()
    return user_out(user)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/auth/change-password")
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(400, "Current password is incorrect.")
    user.hashed_password = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


# ---- team management ----
class TeamIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="agent", pattern="^(admin|agent)$")


@router.get("/team")
def team(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(User).where(User.business_id == user.business_id).order_by(User.id)).scalars()
    return [user_out(u) for u in rows]


@router.post("/team", status_code=201)
def add_member(body: TeamIn, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    if db.execute(select(User).where(func.lower(User.email) == body.email.lower())).scalar_one_or_none():
        raise HTTPException(409, "An account with this email already exists.")
    m = User(business_id=user.business_id, email=body.email.lower(), full_name=body.full_name.strip(),
             hashed_password=hash_password(body.password), role=body.role)
    db.add(m)
    db.commit()
    return user_out(m)


class MemberPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|agent)$")
    is_active: bool | None = None


@router.patch("/team/{member_id}")
def patch_member(member_id: int, body: MemberPatch, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    m = get_owned(db, User, member_id, user.business_id)
    if m.role == "owner":
        raise HTTPException(400, "The owner account cannot be changed.")
    if body.role:
        m.role = body.role
    if body.is_active is not None:
        m.is_active = body.is_active
    db.commit()
    return user_out(m)
