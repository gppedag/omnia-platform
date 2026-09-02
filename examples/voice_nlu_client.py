"""Example integration for a LiveKit/Asterisk STT pipeline.

Send each final STT utterance to CUP; execute only the returned deterministic next_action.
Never let the model create a booking or choose a slot by itself.
"""
import os
import requests

BASE = os.getenv("CUP_BASE_URL", "http://cup-backend:8000")
TOKEN = os.getenv("VOICE_AI_SERVICE_TOKEN", "")


def analyze_utterance(text, call_id=None, session_id=None, failed_understandings=0):
    r = requests.post(
        BASE + "/api/voice/analyze",
        headers={"X-Voice-AI-Token": TOKEN},
        json={
            "text": text,
            "call_id": call_id,
            "session_id": session_id,
            "failed_understandings": failed_understandings,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    print(analyze_utterance("Vorrei prenotare una visita cardiologica privata"))
