"""Esempio integrazione voice agent LiveKit -> CUP learning pipeline.
Non invia audio: invia una trascrizione solo dopo consenso esplicito.
"""
import os
import httpx

BASE = os.getenv("CUP_BASE_URL", "https://demo-cup.ai.basidiai.it").rstrip("/")
TOKEN = os.getenv("TRAINING_SERVICE_TOKEN", "")


def submit_transcript(call_id: int, operator_id: int, transcript: str, consent: bool):
    if not consent:
        return {"ok": False, "skipped": "consent_not_obtained"}
    r = httpx.post(
        BASE + "/api/training/voice-samples",
        headers={"X-CUP-Training-Token": TOKEN},
        json={"call_id": call_id, "operator_id": operator_id, "consent_obtained": True, "transcript": transcript},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def learning_context(query: str):
    r = httpx.get(
        BASE + "/api/training/service-context",
        headers={"X-CUP-Training-Token": TOKEN},
        params={"q": query},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()
