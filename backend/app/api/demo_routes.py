from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db.database import get_db
from app.services.demo_data import seed_demo_data

router = APIRouter(prefix="/api/demo", tags=["demo"])

@router.post("/seed")
def seed(force: bool = False, db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    return seed_demo_data(db, force=force)
