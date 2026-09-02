from __future__ import annotations
import re
from sqlalchemy.orm import Session
from app.models.training import AILearningSample

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?39[ .-]?)?(?:\d[ .-]?){8,12}(?!\w)")
CF_RE = re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.I)


def anonymize(text: str) -> str:
    value = str(text or "")
    value = EMAIL_RE.sub("[EMAIL]", value)
    value = PHONE_RE.sub("[TELEFONO]", value)
    value = CF_RE.sub("[CODICE_FISCALE]", value)
    return value.strip()


def capture_chat_example(db: Session, session, operator_user, operator_text: str):
    previous = None
    for msg in reversed(session.messages):
        if msg.role == "user" and msg.content.strip():
            previous = msg.content.strip()
            break
    if not previous:
        return None
    duplicate = db.query(AILearningSample).filter(
        AILearningSample.source_type == "chat",
        AILearningSample.session_id == session.id,
        AILearningSample.user_text == previous,
        AILearningSample.operator_text == operator_text,
    ).first()
    if duplicate:
        return duplicate
    row = AILearningSample(
        source_type="chat", session_id=session.id, operator_id=getattr(operator_user, "id", None),
        consent_obtained=True, user_text=previous, operator_text=operator_text,
        anonymized_user_text=anonymize(previous), anonymized_operator_text=anonymize(operator_text), status="pending",
    )
    db.add(row)
    return row


def approved_examples(db: Session, query: str, limit: int = 6) -> list[AILearningSample]:
    rows = db.query(AILearningSample).filter(AILearningSample.status == "approved").order_by(AILearningSample.reviewed_at.desc(), AILearningSample.id.desc()).limit(80).all()
    tokens = {x for x in re.findall(r"[a-zà-ù0-9]{4,}", (query or "").lower())}
    def score(r):
        corpus = (r.anonymized_user_text + " " + r.anonymized_operator_text).lower()
        return sum(1 for t in tokens if t in corpus)
    rows.sort(key=lambda r: (score(r), r.id), reverse=True)
    return rows[:limit]


def examples_prompt(db: Session, query: str, limit: int = 6) -> str:
    rows = approved_examples(db, query, limit)
    if not rows:
        return ""
    blocks = []
    for idx, row in enumerate(rows, 1):
        blocks.append(f"Esempio {idx}\nUtente: {row.anonymized_user_text}\nOperatore CUP: {row.anonymized_operator_text}")
    return "\n\nESEMPI APPROVATI DEL METODO CUP (imita metodo, tono e domande; non copiare dati personali):\n" + "\n\n".join(blocks)


def ingest_voice_transcript(db: Session, call_id: int | None, operator_id: int | None, transcript: str, consent: bool) -> int:
    if not consent:
        raise ValueError("Consenso all'utilizzo formativo non acquisito")
    lines = []
    for raw in (transcript or "").splitlines():
        m = re.match(r"\s*(PAZIENTE|UTENTE|CLIENTE|OPERATORE|AGENTE)\s*:\s*(.+)", raw, re.I)
        if m:
            speaker = m.group(1).lower()
            role = "user" if speaker in {"paziente", "utente", "cliente"} else "operator"
            lines.append((role, m.group(2).strip()))
    made = 0
    for i in range(len(lines) - 1):
        if lines[i][0] == "user" and lines[i+1][0] == "operator":
            u, o = lines[i][1], lines[i+1][1]
            if len(u) < 2 or len(o) < 2:
                continue
            row = AILearningSample(source_type="voice", call_id=call_id, operator_id=operator_id,
                consent_obtained=True, user_text=u, operator_text=o,
                anonymized_user_text=anonymize(u), anonymized_operator_text=anonymize(o), status="pending")
            db.add(row); made += 1
    return made
