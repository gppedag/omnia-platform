"""Constrained voice NLU for CUP calls.

The LLM is used only to understand an utterance (intent/entities/sentiment/confidence).
Transactional decisions such as slot availability, prices and booking creation remain in the
existing deterministic CUP services.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("voice_nlu")

ALLOWED_INTENTS = {
    "book_appointment",
    "confirm_appointment",
    "change_appointment",
    "cancel_appointment",
    "availability_price",
    "facility_info",
    "upload_documents",
    "check_appointment",
    "request_operator",
    "checkin_waiting_room",
    "payment_documents",
    "off_topic",
    "unknown",
}

SENTIMENTS = {"positive", "neutral", "confused", "frustrated", "critical"}

DOMAIN_REDIRECT = (
    "Posso aiutarti con prenotazioni, appuntamenti, disponibilita e prezzi, documenti, "
    "pagamenti, check-in e informazioni sulla struttura. Di cosa hai bisogno?"
)

SYSTEM_PROMPT = """Sei il classificatore NLU del voice agent di un CUP sanitario italiano.
Non conversare liberamente e non prendere decisioni operative. Analizza SOLO l'ultima frase del paziente.
Restituisci esclusivamente un oggetto JSON valido, senza markdown.

Intent ammessi:
- book_appointment
- confirm_appointment
- change_appointment
- cancel_appointment
- availability_price
- facility_info
- upload_documents
- check_appointment
- request_operator
- checkin_waiting_room
- payment_documents
- off_topic
- unknown

Sentiment ammessi: positive, neutral, confused, frustrated, critical.
Il sentiment e' solo operativo/customer-care, non una valutazione clinica o psicologica.
Estrai le entita utili quando presenti: service, regime(private|ssn|null), date_preference, time_preference,
doctor, location, booking_reference. Non inventare valori mancanti.
confidence deve essere un numero tra 0 e 1.
Se l'utente parla di argomenti non pertinenti al CUP usa off_topic.
Se chiede esplicitamente un umano usa request_operator.
Se non sei sicuro usa unknown e confidence bassa.
Formato esatto:
{"intent":"...","sentiment":"...","confidence":0.0,"entities":{},"short_summary":"..."}
"""


def llm_available() -> bool:
    return bool(
        getattr(settings, "VOICE_NLU_ENABLED", True)
        and settings.LLM_BASE_URL
        and settings.LLM_MODEL
    )


def _clean_json_text(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    intent = str(raw.get("intent") or "unknown").strip().lower()
    if intent not in ALLOWED_INTENTS:
        intent = "unknown"
    sentiment = str(raw.get("sentiment") or "neutral").strip().lower()
    if sentiment not in SENTIMENTS:
        sentiment = "neutral"
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    entities = raw.get("entities") if isinstance(raw.get("entities"), dict) else {}
    allowed_entities = {
        "service", "regime", "date_preference", "time_preference",
        "doctor", "location", "booking_reference",
    }
    entities = {k: v for k, v in entities.items() if k in allowed_entities and v not in (None, "")}
    regime = entities.get("regime")
    if regime not in (None, "private", "ssn"):
        entities.pop("regime", None)
    return {
        "intent": intent,
        "sentiment": sentiment,
        "confidence": confidence,
        "entities": entities,
        "short_summary": str(raw.get("short_summary") or "")[:500],
    }


def _llm_analyze(text: str, context: list[dict] | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in (context or [])[-6:]:
        role = item.get("role") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": str(content)[:1000]})
    messages.append({"role": "user", "content": text[:5000]})
    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": min(400, max(150, int(settings.LLM_MAX_TOKENS))),
        "response_format": {"type": "json_object"},
    }
    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        with httpx.Client(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=payload)
            # Some OpenAI-compatible servers do not support response_format.
            if response.status_code in {400, 422}:
                payload.pop("response_format", None)
                response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        return _normalize(json.loads(_clean_json_text(content)))
    except Exception as exc:
        logger.warning("Voice NLU LLM non disponibile, fallback regole: %s", exc)
        raise


def _fallback_analyze(text: str) -> dict[str, Any]:
    low = " ".join((text or "").lower().split())
    intent = "unknown"
    confidence = 0.48
    patterns = [
        ("request_operator", ["operatore", "persona", "umano", "parlare con qualcuno"], 0.94),
        ("cancel_appointment", ["disdire", "annullare", "cancellare appuntamento"], 0.91),
        ("change_appointment", ["spostare", "cambiare appuntamento", "riprogrammare"], 0.90),
        ("confirm_appointment", ["confermare", "conferma appuntamento"], 0.90),
        ("book_appointment", ["prenotare", "prenotazione", "vorrei una visita", "fissare una visita"], 0.88),
        ("availability_price", ["disponibilita", "quanto costa", "prezzo", "ticket", "prima data"], 0.87),
        ("upload_documents", ["ricetta", "impegnativa", "caricare", "documento"], 0.84),
        ("check_appointment", ["il mio appuntamento", "quando ho", "verificare appuntamento"], 0.84),
        ("checkin_waiting_room", ["sono arrivato", "sala d'attesa", "check-in", "presenza in sala"], 0.88),
        ("payment_documents", ["pagamento", "pagare", "fattura", "ricevuta", "referto"], 0.82),
        ("facility_info", ["orari", "indirizzo", "parcheggio", "dove siete", "come arrivare"], 0.84),
    ]
    for candidate, terms, score in patterns:
        if any(term in low for term in terms):
            intent, confidence = candidate, score
            break
    off_topic_terms = ["calcio", "meteo", "politica", "ricetta di cucina", "film", "musica", "barzelletta"]
    if any(term in low for term in off_topic_terms):
        intent, confidence = "off_topic", 0.92

    sentiment = "neutral"
    if any(x in low for x in ["arrabbiato", "vergogna", "inaccettabile", "reclamo", "pessimo", "furioso"]):
        sentiment = "critical"
    elif any(x in low for x in ["sono stufo", "frustrato", "non funziona", "ancora", "da ore", "non capite"]):
        sentiment = "frustrated"
    elif any(x in low for x in ["non ho capito", "non capisco", "confuso", "come faccio"]):
        sentiment = "confused"
    elif any(x in low for x in ["grazie", "perfetto", "benissimo", "ottimo"]):
        sentiment = "positive"

    regime = None
    if "ssn" in low or "mutua" in low or "servizio sanitario" in low:
        regime = "ssn"
    elif "privato" in low or "solvenza" in low:
        regime = "private"
    entities = {"regime": regime} if regime else {}
    return _normalize({
        "intent": intent,
        "sentiment": sentiment,
        "confidence": confidence,
        "entities": entities,
        "short_summary": text[:300],
    })


def analyze(text: str, context: list[dict] | None = None) -> dict[str, Any]:
    if not getattr(settings, "VOICE_NLU_ENABLED", True):
        result = _fallback_analyze(text)
        result["engine"] = "rules_disabled"
        return apply_policy(result)
    if llm_available():
        try:
            result = _llm_analyze(text, context)
            result["engine"] = "llm"
            return apply_policy(result)
        except Exception:
            pass
    result = _fallback_analyze(text)
    result["engine"] = "rules_fallback"
    return apply_policy(result)


def apply_policy(result: dict[str, Any], failed_understandings: int = 0) -> dict[str, Any]:
    confidence = float(result.get("confidence") or 0.0)
    sentiment = result.get("sentiment") or "neutral"
    intent = result.get("intent") or "unknown"
    threshold = float(getattr(settings, "VOICE_NLU_CONFIDENCE_THRESHOLD", 0.62))

    handoff = intent == "request_operator"
    handoff_reason = "Richiesta esplicita operatore" if handoff else None
    if sentiment == "critical" and getattr(settings, "VOICE_SENTIMENT_HANDOFF_ENABLED", True):
        handoff = True
        handoff_reason = "Sentiment critico durante la chiamata"
    if failed_understandings >= int(getattr(settings, "VOICE_MAX_UNDERSTANDING_FAILURES", 2)):
        handoff = True
        handoff_reason = "Ripetuti fallimenti di comprensione"

    if handoff:
        next_action = "handoff_operator"
        spoken_reply = "Ti metto in contatto con un operatore. Rimani in linea."
    elif intent == "off_topic":
        next_action = "redirect_to_cup"
        spoken_reply = DOMAIN_REDIRECT
    elif confidence < threshold or intent == "unknown":
        next_action = "clarify_intent"
        spoken_reply = "Non sono sicuro di aver capito. Vuoi prenotare, gestire un appuntamento, chiedere informazioni o parlare con un operatore?"
    else:
        next_action = {
            "book_appointment": "start_booking_flow",
            "confirm_appointment": "confirm_booking_flow",
            "change_appointment": "change_booking_flow",
            "cancel_appointment": "cancel_booking_flow",
            "availability_price": "search_availability_price",
            "facility_info": "facility_info_flow",
            "upload_documents": "document_upload_flow",
            "check_appointment": "lookup_booking_flow",
            "checkin_waiting_room": "checkin_flow",
            "payment_documents": "payment_documents_flow",
        }.get(intent, "clarify_intent")
        spoken_reply = ""

    result.update({
        "next_action": next_action,
        "handoff": handoff,
        "handoff_reason": handoff_reason,
        "spoken_reply": spoken_reply,
        "domain_limited": True,
    })
    return result
