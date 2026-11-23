import re
import unicodedata


_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002500-\U00002BEF"  # cjk
    "]+",
    flags=re.UNICODE,
)

_TASHKEEL = re.compile(r"[\u064B-\u065F\u0670\u0640]")


def strip_emojis(text: str) -> str:
    return _EMOJI_PATTERN.sub("", text)


def normalize_arabic(text: str) -> str:
    text = strip_emojis(text)
    text = _TASHKEEL.sub("", text)
    # Normalize alef variants
    text = text.replace("\u0623", "\u0627")  # أ -> ا
    text = text.replace("\u0625", "\u0627")  # إ -> ا
    text = text.replace("\u0622", "\u0627")  # آ -> ا
    # Normalize ة -> ه
    text = text.replace("\u0629", "\u0647")  # ة -> ه
    # Normalize ي/ى -> ي
    text = text.replace("\u0649", "\u064A")  # ى -> ي
    # Trim and collapse whitespace
    text = " ".join(text.split())
    return text.strip()


def normalize_english(text: str) -> str:
    text = strip_emojis(text)
    text = text.lower()
    # Strip surrounding punctuation
    text = text.strip(".,!?;:\"'()[]{}")
    # Collapse whitespace
    text = " ".join(text.split())
    return text.strip()


def normalize_comment(text: str) -> str:
    """Normalize a comment based on its primary script."""
    text = text.strip()
    if not text:
        return ""
    # Detect if predominantly Arabic
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    total_chars = sum(1 for c in text if c.isalpha())
    if total_chars > 0 and arabic_chars / total_chars > 0.5:
        return normalize_arabic(text)
    return normalize_english(text)
