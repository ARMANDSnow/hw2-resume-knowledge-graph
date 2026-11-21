"""Preserve semantically significant punctuation during evidence checks."""
import hashlib
import unicodedata


def normalize_text(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def validate_quote(page_text, quote):
    normalized = normalize_text(quote or "")
    return bool(normalized) and normalized in normalize_text(page_text)


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()
