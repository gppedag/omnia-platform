import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session


OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 5


def normalize_phone(phone: str) -> str:
    value = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")
    if value.startswith("00"):
        value = "+" + value[2:]
    if value and not value.startswith("+"):
        value = "+39" + value
    return value


def _hash_code(phone: str, code: str) -> str:
    payload = f"{normalize_phone(phone)}:{code}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_challenge(
    db: Session,
    phone: str,
    purpose: str = "login",
    request_ip: str | None = None,
) -> dict:
    phone = normalize_phone(phone)

    if not phone or len(phone) < 8:
        raise ValueError("Numero di telefono non valido")

    now = datetime.utcnow()

    recent = db.execute(
        text("""
            SELECT COUNT(*)
            FROM patient_otp_challenges
            WHERE phone = :phone
              AND created_at > :since
        """),
        {
            "phone": phone,
            "since": now - timedelta(minutes=10),
        },
    ).scalar()

    if recent and recent >= 5:
        raise ValueError("Troppi tentativi. Riprova tra qualche minuto.")

    code = f"{secrets.randbelow(1000000):06d}"
    code_hash = _hash_code(phone, code)

    db.execute(
        text("""
            UPDATE patient_otp_challenges
            SET consumed_at = :now
            WHERE phone = :phone
              AND consumed_at IS NULL
        """),
        {"phone": phone, "now": now},
    )

    row = db.execute(
        text("""
            INSERT INTO patient_otp_challenges
            (
                phone,
                purpose,
                code_hash,
                expires_at,
                attempts,
                max_attempts,
                request_ip
            )
            VALUES
            (
                :phone,
                :purpose,
                :code_hash,
                :expires_at,
                0,
                :max_attempts,
                :request_ip
            )
            RETURNING id
        """),
        {
            "phone": phone,
            "purpose": purpose,
            "code_hash": code_hash,
            "expires_at": now + timedelta(minutes=OTP_TTL_MINUTES),
            "max_attempts": OTP_MAX_ATTEMPTS,
            "request_ip": request_ip,
        },
    ).first()

    db.commit()

    return {
        "challenge_id": row[0],
        "phone": phone,
        "code": code,
        "expires_in": OTP_TTL_MINUTES * 60,
    }


def verify_challenge(
    db: Session,
    challenge_id: int,
    phone: str,
    code: str,
) -> bool:
    phone = normalize_phone(phone)
    now = datetime.utcnow()

    row = db.execute(
        text("""
            SELECT
                id,
                code_hash,
                expires_at,
                attempts,
                max_attempts,
                consumed_at
            FROM patient_otp_challenges
            WHERE id = :challenge_id
              AND phone = :phone
        """),
        {
            "challenge_id": challenge_id,
            "phone": phone,
        },
    ).mappings().first()

    if not row:
        return False

    if row["consumed_at"] is not None:
        return False

    if row["expires_at"] < now:
        return False

    if row["attempts"] >= row["max_attempts"]:
        return False

    expected = row["code_hash"]
    received = _hash_code(phone, code)

    if not hmac.compare_digest(expected, received):
        db.execute(
            text("""
                UPDATE patient_otp_challenges
                SET attempts = attempts + 1
                WHERE id = :challenge_id
            """),
            {"challenge_id": challenge_id},
        )
        db.commit()
        return False

    db.execute(
        text("""
            UPDATE patient_otp_challenges
            SET consumed_at = :now
            WHERE id = :challenge_id
        """),
        {
            "challenge_id": challenge_id,
            "now": now,
        },
    )
    db.commit()

    return True
