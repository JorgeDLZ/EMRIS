import re
import unicodedata


def normalize_name(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", without_accents).strip().upper()


def repair_mojibake(text: str) -> str:
    if "Ã" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return text
