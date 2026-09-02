from fastapi import APIRouter, Depends
from livekit import api as livekit_api

from app.config import settings
from app.auth import get_current_user

router = APIRouter(prefix="/api/livekit", tags=["livekit"])


@router.post("/token")
def create_room_token(room: str = "chatbot-assistenza", user=Depends(get_current_user)):
    """Genera un token LiveKit per far entrare l'utente in una videochiamata col chatbot AI."""
    token = (
        livekit_api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(f"user-{user.id}")
        .with_name(user.full_name)
        .with_grants(livekit_api.VideoGrants(room_join=True, room=room))
    )
    return {"token": token.to_jwt(), "url": settings.LIVEKIT_URL, "room": room}
