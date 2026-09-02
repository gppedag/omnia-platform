from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from app.auth import require_role
from app.config import settings
from app.db.database import get_db
from app.models.training import AILearningSample
from app.services.training_service import ingest_voice_transcript, examples_prompt

router = APIRouter(prefix="/api/training", tags=["ai-training"])

class ReviewPayload(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    notes: str | None = None

class VoicePayload(BaseModel):
    call_id: int | None = None
    operator_id: int | None = None
    consent_obtained: bool = False
    transcript: str = Field(min_length=3, max_length=100000)

@router.get("/samples")
def samples(status: str | None = None, db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    q = db.query(AILearningSample)
    if status: q = q.filter(AILearningSample.status == status)
    rows = q.order_by(AILearningSample.created_at.desc()).limit(300).all()
    return [{"id":r.id,"source_type":r.source_type,"session_id":r.session_id,"call_id":r.call_id,"operator_id":r.operator_id,
             "consent_obtained":r.consent_obtained,"user_text":r.anonymized_user_text,"operator_text":r.anonymized_operator_text,
             "status":r.status,"review_notes":r.review_notes,"created_at":r.created_at} for r in rows]

@router.patch("/samples/{sample_id}")
def review(sample_id:int,payload:ReviewPayload,db:Session=Depends(get_db),user=Depends(require_role("admin"))):
    row=db.get(AILearningSample,sample_id)
    if not row: raise HTTPException(404,"Esempio non trovato")
    row.status=payload.status; row.review_notes=payload.notes; row.reviewed_by=user.id; row.reviewed_at=datetime.now()
    db.commit(); return {"ok":True,"status":row.status}

@router.post("/voice-samples")
def voice(payload:VoicePayload, x_cup_training_token: str | None = Header(default=None), db:Session=Depends(get_db)):
    if not settings.TRAINING_CAPTURE_VOICE_ENABLED:
        raise HTTPException(409,"Raccolta formativa voce disabilitata")
    if settings.TRAINING_REQUIRE_CONSENT and not payload.consent_obtained:
        raise HTTPException(400,"Consenso esplicito richiesto")
    if not settings.TRAINING_SERVICE_TOKEN or x_cup_training_token != settings.TRAINING_SERVICE_TOKEN:
        raise HTTPException(403,"Token servizio training non valido")
    try:
        made=ingest_voice_transcript(db,payload.call_id,payload.operator_id,payload.transcript,payload.consent_obtained)
        db.commit()
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    return {"ok":True,"samples_created":made,"status":"pending_review"}

@router.get("/livekit-context")
def livekit_context(q: str = "", db:Session=Depends(get_db), user=Depends(require_role("admin"))):
    return {"system_prompt": settings.LIVEKIT_TRAINING_SYSTEM_PROMPT, "approved_examples": examples_prompt(db,q,8)}


@router.get("/service-context")
def service_context(q: str = "", x_cup_training_token: str | None = Header(default=None), db:Session=Depends(get_db)):
    if not settings.TRAINING_SERVICE_TOKEN or x_cup_training_token != settings.TRAINING_SERVICE_TOKEN:
        raise HTTPException(403,"Token servizio training non valido")
    return {
        "system_prompt": settings.LIVEKIT_TRAINING_SYSTEM_PROMPT,
        "approved_examples": examples_prompt(db,q,8),
        "consent_required": bool(settings.TRAINING_REQUIRE_CONSENT),
        "voice_capture_enabled": bool(settings.TRAINING_CAPTURE_VOICE_ENABLED),
    }
