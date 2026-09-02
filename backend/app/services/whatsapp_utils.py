import re


def normalize_whatsapp_number(value: str) -> str:
    """
    Restituisce il numero nel formato richiesto dalla WhatsApp Graph API:
    solo cifre, con prefisso internazionale.

    Per i numeri italiani:
      3381398100       -> 393381398100
      +393381398100    -> 393381398100
      00393381398100   -> 393381398100
      393381398100     -> 393381398100
    """

    raw = str(value or "").strip()

    digits = re.sub(r"\D", "", raw)

    if digits.startswith("00"):
        digits = digits[2:]

    if not digits:
        return ""

    # Cellulari italiani salvati senza prefisso internazionale.
    if len(digits) == 10 and digits.startswith("3"):
        digits = "39" + digits

    return digits
