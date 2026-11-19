from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import admin_user, current_business, current_user
from ..models import Business, Integration, User
from ..security import decrypt_json, encrypt_json, hash_api_key, new_api_key, new_webhook_secret
from ..services.emailer import get_smtp_config, send_email
from ..services.llm import llm_configured

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _get(db: Session, bid: int, kind: str) -> Integration | None:
    return db.execute(select(Integration).where(Integration.business_id == bid, Integration.kind == kind)).scalar_one_or_none()


def _mask(v: str) -> str:
    return ("*" * 6 + v[-4:]) if v and len(v) > 4 else ("*" * len(v))


@router.get("")
def status(user: User = Depends(current_user), biz: Business = Depends(current_business), db: Session = Depends(get_db)):
    wa, em = _get(db, biz.id, "whatsapp"), _get(db, biz.id, "email")
    wa_cfg = decrypt_json(wa.config_encrypted) if wa else {}
    base = settings.public_base_url.rstrip("/")
    return {
        "groq": {"configured": llm_configured(), "model": settings.groq_model,
                 "help": "Set GROQ_API_KEY in the server environment (never stored in the database)."},
        "whatsapp": {"configured": bool(wa and wa.enabled and wa_cfg.get("access_token")), "phone_number_id": wa_cfg.get("phone_number_id", ""),
                     "access_token": _mask(wa_cfg.get("access_token", "")), "verify_token": wa_cfg.get("verify_token", ""),
                     "has_app_secret": bool(wa_cfg.get("app_secret")),
                     "webhook_url": f"{base}/api/webhooks/whatsapp/{biz.public_key}"},
        "email": {"configured": get_smtp_config(db, biz.id) is not None, "business_level": bool(em and em.enabled),
                  "host": (decrypt_json(em.config_encrypted).get("host", "") if em else ""),
                  "using_server_default": bool(settings.smtp_host and not (em and em.enabled))},
        "web_widget": {"public_key": biz.public_key,
                       "snippet": f'<script src="{base}/widget.js" data-key="{biz.public_key}" async></script>'},
        "api": {"has_api_key": bool(biz.api_key_hash), "base_url": f"{base}/api/public/v1"},
        "n8n": {"webhook_secret": biz.webhook_secret, "inbound_base": f"{base}/api/webhooks/n8n"},
    }


class WhatsAppIn(BaseModel):
    phone_number_id: str = Field(min_length=3, max_length=50)
    access_token: str | None = Field(default=None, max_length=1000)
    verify_token: str = Field(min_length=6, max_length=100)
    app_secret: str | None = Field(default=None, max_length=200)


@router.put("/whatsapp")
def save_whatsapp(body: WhatsAppIn, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    integ = _get(db, user.business_id, "whatsapp")
    old = decrypt_json(integ.config_encrypted) if integ else {}
    token = body.access_token or old.get("access_token", "")
    if not token:
        raise HTTPException(422, "Access token is required.")
    cfg = {"phone_number_id": body.phone_number_id, "access_token": token, "verify_token": body.verify_token,
           "app_secret": body.app_secret if body.app_secret is not None else old.get("app_secret", "")}
    if integ:
        integ.config_encrypted, integ.enabled = encrypt_json(cfg), True
    else:
        db.add(Integration(business_id=user.business_id, kind="whatsapp", config_encrypted=encrypt_json(cfg)))
    db.commit()
    return {"ok": True}


class EmailIn(BaseModel):
    host: str = Field(min_length=3, max_length=200)
    port: int = Field(default=587, ge=1, le=65535)
    user: str = Field(default="", max_length=200)
    password: str | None = Field(default=None, max_length=300)
    from_email: str = Field(min_length=3, max_length=255)
    use_tls: bool = True


@router.put("/email")
def save_email(body: EmailIn, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    integ = _get(db, user.business_id, "email")
    old = decrypt_json(integ.config_encrypted) if integ else {}
    cfg = body.model_dump()
    cfg["password"] = body.password if body.password is not None else old.get("password", "")
    if integ:
        integ.config_encrypted, integ.enabled = encrypt_json(cfg), True
    else:
        db.add(Integration(business_id=user.business_id, kind="email", config_encrypted=encrypt_json(cfg)))
    db.commit()
    return {"ok": True}


@router.delete("/{kind}")
def remove(kind: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    if kind not in ("whatsapp", "email"):
        raise HTTPException(404, "Unknown integration")
    integ = _get(db, user.business_id, kind)
    if integ:
        db.delete(integ)
        db.commit()
    return {"ok": True}


@router.post("/email/test")
def test_email(user: User = Depends(admin_user), biz: Business = Depends(current_business), db: Session = Depends(get_db)):
    to = biz.notification_email or user.email
    ok, detail = send_email(get_smtp_config(db, biz.id), to, f"[{biz.name}] Test email", "Your email integration works.")
    return {"sent": ok, "detail": detail, "to": to}


@router.post("/api-key")
def regenerate_api_key(user: User = Depends(admin_user), biz: Business = Depends(current_business), db: Session = Depends(get_db)):
    key = new_api_key()
    biz.api_key_hash = hash_api_key(key)
    db.commit()
    return {"api_key": key, "note": "Copy this key now. It is stored hashed and cannot be shown again."}


@router.post("/webhook-secret/rotate")
def rotate_secret(user: User = Depends(admin_user), biz: Business = Depends(current_business), db: Session = Depends(get_db)):
    biz.webhook_secret = new_webhook_secret()
    db.commit()
    return {"webhook_secret": biz.webhook_secret}
