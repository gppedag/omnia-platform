from __future__ import annotations

import re
import unicodedata
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calendar import VisitType


def normalize_service_name(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", (value or "").strip().lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _score(row: VisitType) -> tuple[int, int, int, int]:
    code = (row.code or "").upper()
    return (
        0 if code.startswith("CUP") else 1,
        1 if int(row.private_price_cents or 0) > 0 else 0,
        1 if bool(row.ssn_enabled) else 0,
        -int(row.id or 0),
    )


def merge_duplicate_visit_types(db: Session) -> dict:
    """Merge exact semantic duplicates by normalized display name.

    Keeps the best configured row, repoints dependent records and agenda links,
    then removes redundant rows. Safe to call repeatedly at startup.
    """
    rows = db.query(VisitType).order_by(VisitType.id).all()
    groups: dict[str, list[VisitType]] = {}
    for row in rows:
        key = normalize_service_name(row.name)
        if key:
            groups.setdefault(key, []).append(row)

    merged = 0
    removed_ids: list[int] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        keep = max(group, key=_score)
        duplicates = [r for r in group if r.id != keep.id]
        for dup in duplicates:
            # Preserve richer commercial/configuration data on the surviving row.
            if not keep.private_price_cents and dup.private_price_cents:
                keep.private_price_cents = dup.private_price_cents
            if not keep.ssn_enabled and dup.ssn_enabled:
                keep.ssn_enabled = True
                keep.ssn_ticket_cents = dup.ssn_ticket_cents
            if not keep.ssn_ticket_cents and dup.ssn_ticket_cents:
                keep.ssn_ticket_cents = dup.ssn_ticket_cents
            keep.requires_prescription = bool(keep.requires_prescription or dup.requires_prescription)
            if not keep.notes and dup.notes:
                keep.notes = dup.notes

            # Repoint FK references used across the CUP journey.
            for table in ("bookings", "previsit_templates", "recall_campaigns", "waitlist_entries", "waitlist_offers"):
                db.execute(text(f"UPDATE {table} SET visit_type_id=:keep WHERE visit_type_id=:dup"), {"keep": keep.id, "dup": dup.id})

            # Preserve agenda associations without creating PK duplicates.
            db.execute(text("""
                INSERT INTO agenda_visit_types (agenda_id, visit_type_id)
                SELECT agenda_id, :keep FROM agenda_visit_types WHERE visit_type_id=:dup
                ON CONFLICT DO NOTHING
            """), {"keep": keep.id, "dup": dup.id})
            db.execute(text("DELETE FROM agenda_visit_types WHERE visit_type_id=:dup"), {"dup": dup.id})
            removed_ids.append(dup.id)
            db.delete(dup)
            merged += 1

    if merged:
        db.commit()
    return {"merged": merged, "removed_ids": removed_ids}
