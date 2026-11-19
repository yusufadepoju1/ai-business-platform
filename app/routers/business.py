from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import admin_user, current_business
from ..models import Business, User

router = APIRouter(prefix="/api/business", tags=["business"])


class BusinessIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    industry: str = Field(default="general", max_length=100)
    description: str = Field(default="", max_length=4000)
    website: str = Field(default="", max_length=300)
    phone: str = Field(default="", max_length=50)
    email: str = Field(default="", max_length=255)
    address: str = Field(default="", max_length=300)
    notification_email: str = Field(default="", max_length=255)


def biz_out(b: Business) -> dict:
    return {"id": b.id, "name": b.name, "industry": b.industry, "description": b.description, "website": b.website,
            "phone": b.phone, "email": b.email, "address": b.address, "notification_email": b.notification_email,
            "public_key": b.public_key, "is_demo": b.is_demo}


@router.get("")
def get_business(b: Business = Depends(current_business)):
    return biz_out(b)


@router.put("")
def update_business(body: BusinessIn, b: Business = Depends(current_business), _: User = Depends(admin_user),
                    db: Session = Depends(get_db)):
    for k, v in body.model_dump().items():
        setattr(b, k, v.strip())
    db.commit()
    return biz_out(b)
