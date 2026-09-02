"""Minimal AMI originate helper for human handoff.

It is intentionally optional: a failed AMI connection never breaks chat persistence.
The dialplan/channel values must be adapted to the customer's PBX.
"""
import logging
import panoramisk
from app.config import settings

logger = logging.getLogger("asterisk_gateway")


async def originate_operator_call(session_id: str, caller_number: str = "") -> dict:
    if not settings.ASTERISK_HANDOFF_ENABLED or not settings.OPERATOR_EXTENSION:
        return {"ok": False, "reason": "asterisk_handoff_disabled"}

    manager = panoramisk.Manager(
        host=settings.AMI_HOST,
        port=settings.AMI_PORT,
        username=settings.AMI_USER,
        secret=settings.AMI_PASSWORD,
    )
    try:
        await manager.connect()
        channel = settings.AMI_ORIGINATE_CHANNEL.format(extension=settings.OPERATOR_EXTENSION)
        action = {
            "Action": "Originate",
            "Channel": channel,
            "Context": settings.ASTERISK_CONTEXT,
            "Exten": settings.OPERATOR_EXTENSION,
            "Priority": "1",
            "Async": "true",
            "Variable": f"CUP_CONVERSATION_ID={session_id},CUP_CALLER={caller_number}",
            "CallerID": settings.ASTERISK_CALLER_ID,
        }
        response = await manager.send_action(action)
        return {"ok": True, "response": str(response)}
    except Exception as exc:
        logger.exception("Originate AMI fallito")
        return {"ok": False, "reason": str(exc)}
    finally:
        try:
            manager.close()
        except Exception:
            pass


async def originate_patient_test_call(number: str, prompt: str = "Test CUP AI") -> dict:
    """Origina una chiamata demo verso un paziente.

    Richiede un dialplan Asterisk che, una volta risposta la chiamata, instradi
    ASTERISK_VOICE_TEST_CONTEXT verso il voice agent/LiveKit. Il testo e il numero
    sono passati come variabili AMI e non vengono interpretati dal motore prenotazioni.
    """
    number = "".join(ch for ch in (number or "") if ch.isdigit() or ch == "+")
    if not getattr(settings, "ASTERISK_VOICE_TEST_ENABLED", False):
        return {"ok": False, "reason": "asterisk_voice_test_disabled"}
    if not number:
        return {"ok": False, "reason": "numero_non_valido"}
    manager = panoramisk.Manager(
        host=settings.AMI_HOST, port=settings.AMI_PORT,
        username=settings.AMI_USER, secret=settings.AMI_PASSWORD,
    )
    try:
        await manager.connect()
        channel = settings.ASTERISK_VOICE_TEST_CHANNEL.format(number=number)
        safe_prompt = (prompt or "Test CUP AI").replace("\n", " ")[:300]
        action = {
            "Action": "Originate",
            "Channel": channel,
            "Context": settings.ASTERISK_VOICE_TEST_CONTEXT,
            "Exten": "s",
            "Priority": "1",
            "Async": "true",
            "Variable": f"CUP_TEST_MODE=voice_ai,CUP_TEST_NUMBER={number},CUP_TEST_PROMPT={safe_prompt}",
            "CallerID": settings.ASTERISK_CALLER_ID,
        }
        response = await manager.send_action(action)
        return {"ok": True, "response": str(response), "number": number, "context": settings.ASTERISK_VOICE_TEST_CONTEXT}
    except Exception as exc:
        logger.exception("Originate test paziente AMI fallito")
        return {"ok": False, "reason": str(exc)}
    finally:
        try: manager.close()
        except Exception: pass


# ============================================================
# OMNIA_VOIP_EXTENSION_STATUS_V2
# ============================================================

async def get_extension_status(extension: str) -> dict:
    """
    Stato reale dell'interno Asterisk.

    Per il WebPhone CUP la registrazione SIP avviene sull'endpoint
    PJSIP/<interno>-WS. Viene quindi interrogato prima il device
    WebRTC e, se non disponibile, viene usato PJSIP/<interno>
    come fallback.
    """

    extension = str(extension or "").strip()

    if not extension:
        return {
            "extension": None,
            "registered": False,
            "in_call": False,
            "status": "not_configured",
            "status_text": "Non configurato",
            "asterisk_status": None,
        }

    manager = panoramisk.Manager(
        host=settings.AMI_HOST,
        port=settings.AMI_PORT,
        username=settings.AMI_USER,
        secret=settings.AMI_PASSWORD,
    )

    async def device_state(device):
        response = await manager.send_action({
            "Action": "DeviceState",
            "Device": device,
        })

        state = (
            response.get("State")
            if hasattr(response, "get")
            else None
        )

        return str(state or "UNKNOWN").upper()

    try:
        await manager.connect()

        ws_device = f"PJSIP/{extension}-WS"
        sip_device = f"PJSIP/{extension}"

        ws_state = await device_state(ws_device)

        # UNKNOWN/INVALID => endpoint WS non utilizzabile:
        # fallback sull'endpoint SIP standard.
        if ws_state in ("UNKNOWN", "INVALID"):
            selected_device = sip_device
            state = await device_state(sip_device)
        else:
            selected_device = ws_device
            state = ws_state

        unavailable_states = {
            "UNKNOWN",
            "INVALID",
            "UNAVAILABLE",
        }

        active_states = {
            "INUSE",
            "BUSY",
            "RINGING",
            "RINGINUSE",
            "ONHOLD",
        }

        if state in unavailable_states:
            registered = False
            in_call = False
            normalized = "unavailable"
            label = "Non registrato"

        elif state in active_states:
            registered = True
            in_call = True
            normalized = "active"
            label = "In chiamata"

        else:
            registered = True
            in_call = False
            normalized = "registered"
            label = "Registrato"

        return {
            "extension": extension,
            "registered": registered,
            "in_call": in_call,
            "status": normalized,
            "status_text": label,
            "asterisk_status": state,
            "asterisk_status_text": state,
            "asterisk_device": selected_device,
        }

    except Exception as exc:
        logger.exception(
            "Verifica stato interno %s fallita",
            extension,
        )

        return {
            "extension": extension,
            "registered": False,
            "in_call": False,
            "status": "error",
            "status_text": "Stato non disponibile",
            "asterisk_status": None,
            "error": str(exc),
        }

    finally:
        try:
            manager.close()
        except Exception:
            pass


# ============================================================
# /OMNIA_VOIP_EXTENSION_STATUS_V2
# ============================================================

