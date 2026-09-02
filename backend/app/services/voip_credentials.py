import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet():
    key = os.getenv("VOIP_CREDENTIALS_KEY", "").strip()

    if not key:
        raise RuntimeError(
            "VOIP_CREDENTIALS_KEY non configurata"
        )

    return Fernet(key.encode())


def encrypt_voip_password(value: str | None):
    if not value:
        return None

    return (
        _fernet()
        .encrypt(value.encode())
        .decode()
    )


def decrypt_voip_password(value: str | None):
    if not value:
        return None

    try:
        return (
            _fernet()
            .decrypt(value.encode())
            .decode()
        )
    except InvalidToken as exc:
        raise RuntimeError(
            "Credenziale VoIP non decifrabile"
        ) from exc
