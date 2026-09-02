"""Esempio minimale da integrare nel LiveKit voice agent quando l'LLM richiede un umano."""
import os
import httpx

CUP_BASE_URL = os.getenv("CUP_BASE_URL", "http://cup-backend:8000")
HANDOFF_SERVICE_TOKEN = os.getenv("HANDOFF_SERVICE_TOKEN", "")

async def request_human_operator(*, session_id=None, call_id=None, caller_number=None, reason="Richiesta operatore umano", summary=None):
    headers = {"X-Handoff-Token": HANDOFF_SERVICE_TOKEN}
    payload = {
        "session_id": session_id,
        "call_id": call_id,
        "caller_number": caller_number,
        "source": "livekit",
        "reason": reason,
        "summary": summary,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{CUP_BASE_URL}/api/handoffs/request", json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
