from sqlalchemy import text
from typing import List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db
from app.models.call import Call

import json

from app.models.chat import ChatSession, ChatMessage
from app.models.omnichannel import HandoffEvent
from app.models.patient import Patient
from app.models.user import User
from app.services.channel_service import resolve_patient_for_channel
from app.models.patient import Patient
from app.models.user import User
from app.schemas import CallOut, CallStatusUpdate
from app.auth import get_current_user, require_operator_channel, require_role

router = APIRouter(prefix="/api/calls", tags=["calls"])


class ConnectionManager:
    """Tiene traccia dei client connessi per il broadcast dello stato chiamate."""

    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


@router.delete("/history")
def clear_call_history(
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    """Cancella lo storico delle chiamate. Operazione riservata agli admin."""

    deleted = db.query(Call).delete(synchronize_session=False)
    db.commit()

    return {
        "ok": True,
        "deleted": deleted,
    }



# ============================================================
# OMNIA_OPERATOR_OUTBOUND_RECONCILE_V1
# ============================================================

class OperatorOutboundIn(BaseModel):
    destination: str


@router.post("/operator-outbound")
async def reconcile_operator_outbound(
    payload: OperatorOutboundIn,
    db: Session = Depends(get_db),
    user=Depends(
        require_operator_channel("phone")
    ),
):
    """
    Riconcilia la Call AMI con la destinazione
    realmente composta dal WebPhone.

    AMI/MikoPBX sulla gamba trunk puo' produrre:
        caller_number=<unknown>
        callee_number=202
        direction=inbound

    mentre SIP.js conosce la destinazione reale.
    """

    destination = (
        str(payload.destination or "")
        .strip()
    )

    destination = "".join(
        ch for ch in destination
        if ch.isdigit() or ch == "+"
    )

    if not destination:
        raise HTTPException(
            status_code=400,
            detail="Destinazione non valida",
        )

    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=20)

    # Cerchiamo la Call AMI piu' recente che
    # rappresenta l'operatore WebRTC.
    rows = (
        db.query(Call)
        .filter(
            Call.status.in_(
                ["ringing", "active", "held"]
            )
        )
        .filter(
            Call.started_at >= cutoff
        )
        .order_by(
            Call.started_at.desc()
        )
        .limit(10)
        .all()
    )

    call = None

    for candidate in rows:

        caller = str(
            getattr(
                candidate,
                "caller_number",
                "",
            ) or ""
        ).strip()

        callee = str(
            getattr(
                candidate,
                "callee_number",
                "",
            ) or ""
        ).strip()

        operator_extension = str(
            getattr(
                candidate,
                "operator_extension",
                "",
            ) or ""
        ).strip()

        call_type = str(
            getattr(
                candidate,
                "call_type",
                "",
            ) or ""
        ).strip().lower()

        # La forma osservata realmente:
        # <unknown> -> 202, call_type operator
        if (
            call_type == "operator"
            or operator_extension
            or caller.lower() in {
                "",
                "<unknown>",
                "unknown",
            }
        ):
            call = candidate
            break

    if not call:
        return {
            "ok": False,
            "pending": True,
            "destination": destination,
            "message": "Call AMI non ancora disponibile",
        }

    operator_extension = str(
        getattr(
            call,
            "operator_extension",
            "",
        ) or ""
    ).strip()

    if not operator_extension:

        current_callee = str(
            getattr(
                call,
                "callee_number",
                "",
            ) or ""
        ).strip()

        if current_callee.isdigit():
            operator_extension = current_callee

    if not operator_extension:

        current_caller = str(
            getattr(
                call,
                "caller_number",
                "",
            ) or ""
        ).strip()

        if current_caller.isdigit():
            operator_extension = current_caller

    # Correzione autorevole.
    call.direction = "outbound"
    call.call_type = "operator"

    if operator_extension:
        call.operator_extension = (
            operator_extension
        )

        call.caller_number = (
            operator_extension
        )

    call.callee_number = destination

    db.commit()
    db.refresh(call)

    await manager.broadcast({
        "type": "call_updated",
        "call_id": call.id,
        "caller_number":
            call.caller_number,
        "callee_number":
            call.callee_number,
        "channel":
            call.channel,
        "status":
            call.status,
        "asterisk_linkedid":
            call.asterisk_linkedid,
        "call_type":
            call.call_type,
        "operator_extension":
            call.operator_extension,
        "patient_id":
            call.patient_id,
        "direction":
            call.direction,
    })

    return {
        "ok": True,
        "pending": False,
        "call_id": call.id,
        "direction": call.direction,
        "caller_number":
            call.caller_number,
        "callee_number":
            call.callee_number,
        "operator_extension":
            call.operator_extension,
    }

# /OMNIA_OPERATOR_OUTBOUND_RECONCILE_V1


@router.get("/", response_model=List[CallOut])
def list_calls(db: Session = Depends(get_db), user=Depends(require_operator_channel("phone"))):
    return db.query(Call).order_by(Call.started_at.desc()).limit(200).all()


# OMNIA_VOICE_REGISTRY_V1


# OMNIA_VOICE_REGISTRY_V2

@router.get("/voice-registry")
def voice_registry(
    limit: int = 200,
    db: Session = Depends(get_db),
    user=Depends(
        require_operator_channel("phone")
    ),
):
    """
    Registro unificato Omnia Voice.

    La Call e' l'entita' principale.

    Per ogni chiamata vengono restituiti:
    - stato realtime
    - tipo AI / operatore
    - paziente
    - sessione omnicanale
    - trascrizione limitata alla finestra
      temporale della singola chiamata
    - metriche AI
    """

    limit = max(
        1,
        min(int(limit or 200), 500)
    )

    now = datetime.utcnow()

    calls = (
        db.query(Call)
        .order_by(Call.started_at.desc())
        .limit(limit)
        .all()
    )

    result = []

    for call in calls:

        # --------------------------------------------------
        # SESSIONE COLLEGATA ALLA CALL
        # --------------------------------------------------

        handoff_event = (
            db.query(HandoffEvent)
            .filter(
                HandoffEvent.call_id == call.id
            )
            .order_by(
                HandoffEvent.created_at.desc(),
                HandoffEvent.id.desc(),
            )
            .first()
        )

        session = None

        if handoff_event:
            session = (
                db.query(ChatSession)
                .filter(
                    ChatSession.id ==
                    handoff_event.session_id
                )
                .first()
            )


        # --------------------------------------------------
        # RICONCILIAZIONE PAZIENTE
        # --------------------------------------------------

        patient = None

        patient_id = (
            getattr(
                call,
                "patient_id",
                None
            )
            or (
                session.patient_id
                if session
                else None
            )
        )


        if patient_id:

            patient = (
                db.query(Patient)
                .filter(
                    Patient.id == patient_id
                )
                .first()
            )


        # OMNIA_VOICE_REMOTE_PATIENT_LOOKUP_V1
        #
        # Il numero remoto dipende dalla direzione:
        # - inbound  -> caller_number
        # - outbound -> callee_number
        direction = str(
            getattr(
                call,
                "direction",
                "inbound",
            ) or "inbound"
        ).lower()

        remote_number = (
            call.callee_number
            if direction == "outbound"
            else call.caller_number
        )

        remote_number = str(
            remote_number or ""
        ).strip()

        if (
            not patient
            and remote_number
            and remote_number.lower()
                not in {
                    "<unknown>",
                    "unknown",
                    ""
                }
        ):

            try:
                patient = (
                    resolve_patient_for_channel(
                        db,
                        "phone",
                        remote_number,
                    )
                )
            except Exception:
                patient = None


        if patient:

            patient_id = patient.id

            if (
                hasattr(call, "patient_id")
                and not getattr(
                    call,
                    "patient_id",
                    None
                )
            ):
                call.patient_id = patient.id

            if (
                session
                and not session.patient_id
            ):
                session.patient_id = patient.id


        patient_user = None

        if patient:
            patient_user = (
                db.query(User)
                .filter(
                    User.id == patient.user_id
                )
                .first()
            )


        # --------------------------------------------------
        # TRASCRIZIONE DELLA SINGOLA CALL
        # --------------------------------------------------

        messages = []

        if session and call.started_at:

            window_start = (
                call.started_at
                - timedelta(seconds=5)
            )

            # LIVE:
            # arriviamo fino ad ora.
            #
            # CONCLUSA:
            # piccolo margine dopo hangup per eventuali
            # transcript finali asincroni.
            window_end = (
                call.ended_at
                if call.ended_at
                else now
            ) + timedelta(seconds=8)


            rows = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.session_id ==
                    session.id,
                    ChatMessage.created_at >=
                    window_start,
                    ChatMessage.created_at <=
                    window_end,
                )
                .order_by(
                    ChatMessage.created_at.asc(),
                    ChatMessage.id.asc(),
                )
                .all()
            )


            messages = [
                {
                    "id": row.id,
                    "role": row.role,
                    "content": row.content,
                    "created_at":
                        row.created_at,
                }
                for row in rows
            ]


        # --------------------------------------------------
        # OMNIA_OPERATOR_TRANSCRIPT_V1
        # Trascrizione STT specifica della Call.
        #
        # Per le chiamate operatore ha precedenza
        # sui ChatMessage della sessione condivisa.
        # --------------------------------------------------

        if (
            getattr(
                call,
                "call_type",
                None
            ) == "operator"
        ):

            transcript_rows = (
                db.execute(
                    text("""
                        SELECT
                            id,
                            speaker,
                            content,
                            started_ms,
                            ended_ms,
                            confidence,
                            created_at
                        FROM
                            call_transcript_segments
                        WHERE
                            call_id=:call_id
                        ORDER BY
                            started_ms ASC,
                            id ASC
                    """),
                    {
                        "call_id":
                            call.id
                    },
                )
                .mappings()
                .all()
            )


            if transcript_rows:

                messages = [
                    {
                        "id":
                            f"stt-{row['id']}",

                        "role":
                            (
                                "user"
                                if row["speaker"]
                                   == "patient"
                                else "operator"
                            ),

                        "speaker":
                            row["speaker"],

                        "content":
                            row["content"],

                        "started_ms":
                            row["started_ms"],

                        "ended_ms":
                            row["ended_ms"],

                        "confidence":
                            row["confidence"],

                        "created_at":
                            row["created_at"],
                    }

                    for row
                    in transcript_rows
                ]

        # --------------------------------------------------
        # VOICE CONTEXT
        # --------------------------------------------------

        session_voice = {}

        if session:

            try:
                ctx = json.loads(
                    session.context_json
                    or "{}"
                )

                if isinstance(ctx, dict):
                    candidate = ctx.get(
                        "voice"
                    )

                    if isinstance(
                        candidate,
                        dict
                    ):
                        session_voice = candidate

            except Exception:
                pass


        confidence = getattr(
            call,
            "ai_confidence",
            None
        )

        # Il frontend storico usa 0..1.
        confidence_normalized = None

        if confidence is not None:

            try:
                confidence_normalized = (
                    float(confidence) / 100.0
                    if float(confidence) > 1
                    else float(confidence)
                )
            except Exception:
                confidence_normalized = None


        status = (
            getattr(call, "status", None)
            or "unknown"
        )

        live = status in {
            "ringing",
            "active",
            "held",
        }


        duration_seconds = getattr(
            call,
            "duration_seconds",
            None
        )

        if live and call.started_at:

            duration_from = (
                getattr(
                    call,
                    "answered_at",
                    None
                )
                or call.started_at
            )

            duration_seconds = max(
                0,
                int(
                    (
                        now -
                        duration_from
                    ).total_seconds()
                )
            )


        voice = {
            "intent":
                getattr(
                    call,
                    "ai_intent",
                    None
                )
                or session_voice.get(
                    "intent"
                ),

            "sentiment":
                getattr(
                    call,
                    "ai_sentiment",
                    None
                )
                or session_voice.get(
                    "sentiment"
                ),

            "sentiment_overall":
                getattr(
                    call,
                    "ai_sentiment",
                    None
                )
                or session_voice.get(
                    "sentiment_overall"
                )
                or session_voice.get(
                    "sentiment"
                ),

            "sentiment_trend":
                session_voice.get(
                    "sentiment_trend"
                ),

            "confidence":
                confidence_normalized
                if confidence_normalized
                   is not None
                else session_voice.get(
                    "confidence"
                ),

            "handoff":
                bool(
                    session_voice.get(
                        "handoff"
                    )
                ),

            "handoff_reason":
                session_voice.get(
                    "handoff_reason"
                ),

            "short_summary":
                getattr(
                    call,
                    "ai_last_summary",
                    None
                )
                or session_voice.get(
                    "short_summary"
                ),
        }


        result.append({
            "id": call.id,

            "caller_number":
                call.caller_number,

            "callee_number":
                call.callee_number,

            "channel":
                getattr(
                    call,
                    "channel",
                    "phone"
                ),

            "status":
                status,

            "live":
                live,

            "started_at":
                call.started_at,

            "answered_at":
                getattr(
                    call,
                    "answered_at",
                    None
                ),

            "ended_at":
                call.ended_at,

            "duration_seconds":
                duration_seconds,

            "source":
                getattr(
                    call,
                    "source",
                    "asterisk"
                ),

            "direction":
                getattr(
                    call,
                    "direction",
                    "inbound"
                ),

            "call_type":
                getattr(
                    call,
                    "call_type",
                    "unknown"
                ),

            "operator_extension":
                getattr(
                    call,
                    "operator_extension",
                    None
                ),

            "patient_id":
                patient_id,

            "patient_name":
                (
                    patient_user.full_name
                    if patient_user
                    else None
                ),

            "patient": (
                {
                    "id": patient.id,
                    "full_name":
                        patient_user.full_name
                        if patient_user
                        else None,
                    "phone":
                        patient_user.phone
                        if patient_user
                        else None,
                    "email":
                        patient_user.email
                        if patient_user
                        else None,
                }
                if patient
                else None
            ),

            "session_id":
                session.id
                if session
                else None,

            "session_status":
                session.status
                if session
                else None,

            # OMNIA_VOICE_REMOTE_IDENTITY_V17
            #
            # sender_id rappresenta l'interlocutore remoto:
            # inbound  -> caller
            # outbound -> callee
            "sender_id":
                (
                    session.sender_id
                    if session
                    else (
                        call.callee_number
                        if str(
                            getattr(
                                call,
                                "direction",
                                "inbound",
                            ) or "inbound"
                        ).lower() == "outbound"
                        else call.caller_number
                    )
                ),

            "messages":
                messages,

            "message_count":
                len(messages),

            "voice":
                voice,

            "asterisk_uniqueid":
                getattr(
                    call,
                    "asterisk_uniqueid",
                    None
                ),

            "asterisk_linkedid":
                getattr(
                    call,
                    "asterisk_linkedid",
                    None
                ),

            # Compatibilita'
            "ai_intent":
                voice["intent"],

            "ai_sentiment":
                voice["sentiment"],

            "ai_confidence":
                confidence,

            "ai_last_summary":
                voice["short_summary"],
        })


    # Salva eventuale riconciliazione paziente
    # effettuata durante la lettura.
    db.commit()

    return {
        "items": result
    }

@router.patch("/{call_id}/status", response_model=CallOut)
async def update_call_status(call_id: int, payload: CallStatusUpdate, db: Session = Depends(get_db),
                              user=Depends(require_operator_channel("phone"))):
    call = db.query(Call).get(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Chiamata non trovata")
    call.status = payload.status
    if payload.status == "ended":
        call.ended_at = datetime.utcnow()
        if call.started_at:
            call.duration_seconds = int((call.ended_at - call.started_at).total_seconds())
    db.commit()
    db.refresh(call)

    await manager.broadcast({
        "type": "call_status",
        "call_id": call.id,
        "status": call.status,
        "duration_seconds": call.duration_seconds,
    })
    return call


@router.websocket("/ws")
async def calls_websocket(ws: WebSocket):
    """Canale websocket opzionale per lo stato chiamate in tempo reale."""
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # ping/keepalive dal client
    except WebSocketDisconnect:
        manager.disconnect(ws)
