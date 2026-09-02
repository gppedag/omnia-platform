"""
Listener Asterisk AMI per integrazione telefonica CUP.

Riceve gli eventi AMI da MikoPBX/Asterisk, correla le diverse gambe
della stessa chiamata tramite Linkedid e aggiorna la tabella calls.

Obiettivi:
- una sola riga DB per ogni chiamata reale;
- caller_number = numero esterno;
- callee_number = interno operatore, es. 201;
- aggiornamento stato ringing -> active -> ended;
- broadcast realtime verso /api/calls/ws;
- creazione del Journey omnicanale senza bloccare la persistenza telefonica.
"""

import asyncio
import logging
import re
from datetime import datetime

import panoramisk

from app.config import settings
from app.db.database import SessionLocal
from app.models.call import Call
from app.models.user import User
from app.models.patient import Patient
from app.models.omnichannel import HandoffEvent
from app.services.channel_service import get_or_create_session
from app.api.call_routes import manager as calls_ws_manager


logger = logging.getLogger("ami_listener")


def _event_value(event, key, default=""):
    try:
        return event.get(key, default) or default
    except Exception:
        return default


def _valid_number(value):
    if not value:
        return False

    value = str(value).strip()

    if value.lower() in (
        "<unknown>",
        "unknown",
        "none",
        "anonymous",
    ):
        return False

    return True


def _find_call_by_linkedid(db, linkedid, include_ended=False):
    if not linkedid:
        return None

    query = db.query(Call).filter(
        Call.asterisk_linkedid == linkedid,
    )

    if not include_ended:
        query = query.filter(Call.status != "ended")

    return query.order_by(Call.id.desc()).first()


# OMNIA_VOICE_AMI_V1

def _omnia_phone_digits(value):
    digits = re.sub(r"\D", "", str(value or ""))

    # Normalizza +39 / 0039 / 39
    if digits.startswith("39") and len(digits) > 10:
        digits = digits[2:]

    return digits


def _omnia_find_patient_by_phone(db, number):
    wanted = _omnia_phone_digits(number)

    if not wanted:
        return None

    users = (
        db.query(User)
        .filter(User.phone.isnot(None))
        .all()
    )

    for user in users:
        if _omnia_phone_digits(user.phone) == wanted:
            return (
                db.query(Patient)
                .filter(Patient.user_id == user.id)
                .first()
            )

    return None


def _omnia_classify_leg(
    call,
    channel_name="",
    exten="",
    connected="",
    caller=""
):
    channel_name = str(channel_name or "")

    values = {
        str(exten or "").strip(),
        str(connected or "").strip(),
        str(caller or "").strip(),
    }

    changed = False

    # Voice AI:
    # nei test reali compare PJSIP/livekit-local
    # e la destinazione interna e' 9000.
    if (
        "livekit-local" in channel_name.lower()
        or "9000" in values
    ):
        if call.call_type != "voice_ai":
            call.call_type = "voice_ai"
            changed = True

        if call.callee_number != "9000":
            call.callee_number = "9000"
            changed = True

        return changed

    # Operatore WebRTC:
    # PJSIP/201-WS-000000xx
    match = re.search(
        r"PJSIP/(\d+)-WS-",
        channel_name,
        re.I
    )

    if match:
        extension = match.group(1)

        if call.call_type != "operator":
            call.call_type = "operator"
            changed = True

        if call.operator_extension != extension:
            call.operator_extension = extension
            changed = True

        # OMNIA_OUTBOUND_PROTECT_V1
        #
        # In una outbound l'estensione WebRTC e'
        # l'OPERATORE, non il destinatario.
        #
        # Non dobbiamo quindi distruggere il numero
        # remoto gia' riconciliato dal WebPhone.
        if (
            str(
                getattr(
                    call,
                    "direction",
                    "inbound",
                ) or "inbound"
            ).lower()
            != "outbound"
        ):
            if call.callee_number != extension:
                call.callee_number = extension
                changed = True

    return changed


async def _broadcast_call(event_type, call, linkedid):
    """
    Invia al frontend CUP lo stato corrente della chiamata.

    Il broadcast non persiste nulla: il database resta la fonte
    autorevole dello stato.
    """
    payload = {
        "type": event_type,
        "call_id": call.id,
        "caller_number": call.caller_number,
        "callee_number": call.callee_number,
        "channel": call.channel,
        "status": call.status,
        "asterisk_linkedid": linkedid,
        "call_type": getattr(call, "call_type", "unknown"),
        "operator_extension": getattr(call, "operator_extension", None),
        "patient_id": getattr(call, "patient_id", None),
    }

    if call.duration_seconds is not None:
        payload["duration_seconds"] = call.duration_seconds

    await calls_ws_manager.broadcast(payload)


async def _on_event(manager, event):
    # Con la versione Panoramisk utilizzata nel progetto il nome
    # dell'evento arriva nel campo "Event".
    event_name = (
        _event_value(event, "Event")
        or getattr(event, "name", "")
        or ""
    )

    channel_name = _event_value(event, "Channel")
    caller = _event_value(event, "CallerIDNum")
    connected = _event_value(event, "ConnectedLineNum")
    exten = _event_value(event, "Exten")
    uniqueid = _event_value(event, "Uniqueid")
    linkedid = _event_value(event, "Linkedid")

    interesting_events = (
        "Newchannel",
        "Newstate",
        "DialBegin",
        "DialEnd",
        "Bridge",
        "BridgeEnter",
        "BridgeLeave",
        "Hangup",
    )

    if event_name in interesting_events:
        logger.info(
            "AMI event=%s channel=%s caller=%s connected=%s "
            "exten=%s uniqueid=%s linkedid=%s",
            event_name,
            channel_name,
            caller,
            connected,
            exten,
            uniqueid,
            linkedid,
        )

    db = SessionLocal()

    try:
        # Classifica la destinazione osservando tutte
        # le gambe Asterisk con lo stesso Linkedid.
        if linkedid and event_name != "Newchannel":

            omnia_call = _find_call_by_linkedid(
                db,
                linkedid,
                include_ended=True,
            )

            if omnia_call:

                changed = _omnia_classify_leg(
                    omnia_call,
                    channel_name,
                    exten,
                    connected,
                    caller,
                )

                if changed:

                    db.commit()
                    db.refresh(omnia_call)

                    await _broadcast_call(
                        "call_updated",
                        omnia_call,
                        linkedid,
                    )

        # =========================================================
        # NEWCHANNEL
        # =========================================================
        if event_name == "Newchannel":
            is_trunk = "SIP-TRUNK" in channel_name
            is_webrtc = "-WS-" in channel_name

            existing = _find_call_by_linkedid(
                db,
                linkedid,
                include_ended=False,
            )

            # -----------------------------------------------------
            # Seconda gamba Asterisk della stessa telefonata.
            # Non viene creato un nuovo record.
            # -----------------------------------------------------
            if existing:
                changed = False

                # Su PJSIP/201-WS CallerIDNum=201 rappresenta
                # l'interno chiamato, non il vero caller.
                # OMNIA_OUTBOUND_STICKY_V2
                #
                # Una Call riconciliata come outbound non deve più
                # perdere il numero remoto a favore dell'interno.
                is_outbound = (
                    str(
                        getattr(
                            existing,
                            "direction",
                            "inbound",
                        ) or "inbound"
                    ).lower()
                    == "outbound"
                )

                if (
                    not is_outbound
                    and is_webrtc
                    and _valid_number(caller)
                ):
                    clean_caller = str(caller).strip()

                    if clean_caller.isdigit():
                        if existing.callee_number != clean_caller:
                            existing.callee_number = clean_caller
                            changed = True

                # ConnectedLineNum può contenere l'interno.
                # Non deve sovrascrivere il remoto di una outbound.
                if (
                    not is_outbound
                    and _valid_number(connected)
                ):
                    clean_connected = str(connected).strip()

                    if clean_connected.isdigit():
                        if existing.callee_number != clean_connected:
                            existing.callee_number = clean_connected
                            changed = True

                if changed:
                    db.commit()
                    db.refresh(existing)

                    await _broadcast_call(
                        "call_updated",
                        existing,
                        linkedid,
                    )

                    logger.info(
                        "CALL UPDATED id=%s linkedid=%s "
                        "caller=%s callee=%s",
                        existing.id,
                        linkedid,
                        existing.caller_number,
                        existing.callee_number,
                    )

                return

            # -----------------------------------------------------
            # La gamba WebRTC non deve creare autonomamente
            # la chiamata principale.
            # -----------------------------------------------------
            if is_webrtc:
                logger.info(
                    "AMI WebRTC leg ignored linkedid=%s "
                    "caller=%s channel=%s",
                    linkedid,
                    caller,
                    channel_name,
                )
                return

            # -----------------------------------------------------
            # Determinazione caller/callee.
            # -----------------------------------------------------
            if is_trunk:
                real_caller = caller

                if _valid_number(connected):
                    real_callee = str(connected).strip()
                elif _valid_number(exten):
                    real_callee = str(exten).strip()
                else:
                    real_callee = ""

            else:
                real_caller = caller

                if _valid_number(connected):
                    real_callee = str(connected).strip()
                elif _valid_number(exten):
                    real_callee = str(exten).strip()
                else:
                    real_callee = ""

            # -----------------------------------------------------
            # Creazione della chiamata principale.
            # -----------------------------------------------------
            patient = _omnia_find_patient_by_phone(
                db,
                real_caller,
            )

            call = Call(
                caller_number=real_caller,
                callee_number=real_callee,
                channel=channel_name,
                status="ringing",
                asterisk_linkedid=linkedid,
                asterisk_uniqueid=uniqueid or None,
                source="asterisk",
                direction="inbound",
                call_type="unknown",
                patient_id=patient.id if patient else None,
            )

            db.add(call)
            db.commit()
            db.refresh(call)

            await _broadcast_call(
                "call_created",
                call,
                linkedid,
            )

            logger.info(
                "CALL CREATED id=%s linkedid=%s caller=%s "
                "callee=%s channel=%s",
                call.id,
                linkedid,
                call.caller_number,
                call.callee_number,
                call.channel,
            )

            # -----------------------------------------------------
            # Journey omnicanale.
            #
            # Un errore qui non deve eliminare la chiamata
            # già registrata nel database.
            # -----------------------------------------------------
            if _valid_number(real_caller):
                try:
                    session = get_or_create_session(
                        db,
                        "phone",
                        real_caller,
                        real_caller,
                        {
                            "asterisk_channel": channel_name,
                            "asterisk_uniqueid": uniqueid,
                            "asterisk_linkedid": linkedid,
                            "call_id": call.id,
                            "direction": "inbound",
                        },
                    )

                    session.status = "bot"

                    db.add(
                        HandoffEvent(
                            session_id=session.id,
                            event="phone_started",
                            from_owner="customer",
                            to_owner="llm",
                            reason="Chiamata entrante via MikoPBX",
                            call_id=call.id,
                        )
                    )

                    db.commit()

                except Exception:
                    db.rollback()

                    logger.exception(
                        "Errore Journey telefonico call_id=%s",
                        call.id,
                    )

        # =========================================================
        # DIALBEGIN
        # =========================================================
        elif event_name == "DialBegin":
            call = _find_call_by_linkedid(
                db,
                linkedid,
                include_ended=False,
            )

            if not call:
                return

            dest_channel = _event_value(event, "DestChannel")
            dest_caller = _event_value(event, "DestCallerIDNum")
            dest_connected = _event_value(
                event,
                "DestConnectedLineNum",
            )

            candidate = ""

            if _valid_number(dest_connected):
                candidate = str(dest_connected).strip()

            elif _valid_number(dest_caller):
                candidate = str(dest_caller).strip()

            # Estrazione dell'interno da:
            # PJSIP/201-WS-000000xx
            if "-WS-" in dest_channel:
                try:
                    endpoint_part = dest_channel.split("/", 1)[1]
                    endpoint_name = endpoint_part.split("-WS-", 1)[0]

                    if endpoint_name.isdigit():
                        candidate = endpoint_name

                except Exception:
                    pass

            if candidate and candidate.isdigit():
                changed = call.callee_number != candidate

                call.callee_number = candidate
                db.commit()
                db.refresh(call)

                if changed:
                    await _broadcast_call(
                        "call_updated",
                        call,
                        linkedid,
                    )

                logger.info(
                    "CALL DIALED id=%s linkedid=%s callee=%s",
                    call.id,
                    linkedid,
                    candidate,
                )

        # =========================================================
        # BRIDGE / BRIDGEENTER
        # =========================================================
        elif event_name in ("Bridge", "BridgeEnter"):
            call = _find_call_by_linkedid(
                db,
                linkedid,
                include_ended=False,
            )

            if not call:
                return

            if call.status != "active":
                call.status = "active"

                if not call.answered_at:
                    call.answered_at = datetime.utcnow()

                db.commit()
                db.refresh(call)

                await _broadcast_call(
                    "call_active",
                    call,
                    linkedid,
                )

                logger.info(
                    "CALL ACTIVE id=%s linkedid=%s "
                    "caller=%s callee=%s",
                    call.id,
                    linkedid,
                    call.caller_number,
                    call.callee_number,
                )

        # =========================================================
        # HANGUP
        # =========================================================
        elif event_name == "Hangup":

            # I canali Local dell'IVR vengono chiusi
            # prima della telefonata reale.
            if channel_name.startswith("Local/"):

                logger.info(
                    "OMNIA helper Hangup ignored "
                    "channel=%s linkedid=%s",
                    channel_name,
                    linkedid,
                )

                return

            call = _find_call_by_linkedid(
                db,
                linkedid,
                include_ended=False,
            )

            if not call:
                return

            # OMNIA_VOICE_MISSED_V1
            now = datetime.utcnow()

            # Se non siamo mai entrati realmente in conversazione,
            # la telefonata e' una chiamata persa.
            call.status = (
                "ended"
                if call.answered_at
                else "missed"
            )

            call.ended_at = now

            duration_start = (
                call.answered_at
                or call.started_at
            )

            if duration_start:
                try:
                    call.duration_seconds = max(
                        0,
                        int(
                            (
                                now - duration_start
                            ).total_seconds()
                        ),
                    )

                except Exception:
                    pass

            db.commit()
            db.refresh(call)

            await _broadcast_call(
                "call_ended",
                call,
                linkedid,
            )

            logger.info(
                "CALL ENDED id=%s linkedid=%s "
                "caller=%s callee=%s duration=%s",
                call.id,
                linkedid,
                call.caller_number,
                call.callee_number,
                call.duration_seconds,
            )

    except Exception:
        db.rollback()

        logger.exception(
            "Errore durante gestione evento AMI %s "
            "channel=%s linkedid=%s",
            event_name,
            channel_name,
            linkedid,
        )

    finally:
        db.close()


async def start_ami_listener():
    while True:
        manager = panoramisk.Manager(
            host=settings.AMI_HOST,
            port=settings.AMI_PORT,
            username=settings.AMI_USER,
            secret=settings.AMI_PASSWORD,
        )

        manager.register_event("*", _on_event)

        try:
            await manager.connect()

            logger.info(
                "Connesso ad Asterisk AMI su %s:%s",
                settings.AMI_HOST,
                settings.AMI_PORT,
            )

            while getattr(manager, "connected", True):
                await asyncio.sleep(10)

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Impossibile connettersi ad Asterisk AMI "
                "(%s:%s). Nuovo tentativo tra 10 secondi.",
                settings.AMI_HOST,
                settings.AMI_PORT,
            )

        await asyncio.sleep(10)
