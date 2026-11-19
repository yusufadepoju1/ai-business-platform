from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import Business, User
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(401, "Not authenticated")
    data = decode_access_token(creds.credentials)
    if not data:
        raise HTTPException(401, "Session expired. Please sign in again.")
    user = db.get(User, int(data["sub"]))
    if not user or not user.is_active or user.business_id != data.get("bid"):
        raise HTTPException(401, "Account not found or disabled")
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "You do not have permission to do this.")
        return user
    return dep


admin_user = require_roles("owner", "admin")


def current_business(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Business:
    return db.get(Business, user.business_id)


def get_owned(db: Session, model, obj_id: int, business_id: int):
    """Tenant-scoped fetch: 404 when the record belongs to another business."""
    obj = db.get(model, obj_id)
    if not obj or getattr(obj, "business_id", None) != business_id:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj
