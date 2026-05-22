from __future__ import annotations

import html
import re
from hashlib import sha256


ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
HTML_TAGS = re.compile(r"<[^>]+>")
ARABIC_CHARS = re.compile(r"[\u0600-\u06ff]")
LATIN_CHARS = re.compile(r"[A-Za-z]")
EMAILS = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
HANDLES = re.compile(r"(?<!\w)@[\w.]{2,}")
PHONE_NUMBERS = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
URLS = re.compile(r"https?://\S+|www\.\S+")
SPACE = re.compile(r"\s+")


def normalize_text(text: str, max_chars: int = 4000) -> str:
    cleaned = html.unescape(HTML_TAGS.sub(" ", text))
    cleaned = ARABIC_DIACRITICS.sub("", cleaned)
    cleaned = (
        cleaned.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ـ", "")
    )
    cleaned = SPACE.sub(" ", cleaned).strip()
    return cleaned[:max_chars]


def detect_language(text: str) -> str:
    arabic_count = len(ARABIC_CHARS.findall(text))
    latin_count = len(LATIN_CHARS.findall(text))
    total_script_chars = arabic_count + latin_count
    if arabic_count >= 3 and arabic_count / max(total_script_chars, 1) >= 0.25:
        return "ar"
    if latin_count:
        return "en"
    return "unknown"


def minimize_for_hosted_ai(text: str, max_chars: int = 1200) -> str:
    minimized = normalize_text(text, max_chars=max_chars)
    minimized = EMAILS.sub("[email]", minimized)
    minimized = PHONE_NUMBERS.sub("[phone]", minimized)
    minimized = HANDLES.sub("[handle]", minimized)
    minimized = URLS.sub("[url]", minimized)
    return minimized[:max_chars]


def content_hash(text: str) -> str:
    folded = normalize_text(text, max_chars=2000).casefold()
    folded = URLS.sub("", folded)
    return sha256(SPACE.sub(" ", folded).strip().encode("utf-8")).hexdigest()


def dedupe_key(platform: str, source_id: int, external_id: str | None, text: str) -> str:
    stable_id = external_id or content_hash(text)
    material = f"{platform}:{source_id}:{stable_id}"
    return sha256(material.encode("utf-8")).hexdigest()


def snippet(text: str, max_chars: int = 360) -> str:
    normalized = normalize_text(text, max_chars=max_chars + 1)
    return normalized if len(normalized) <= max_chars else f"{normalized[:max_chars].rstrip()}..."
