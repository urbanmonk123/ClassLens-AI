from __future__ import annotations

import os
from urllib.parse import urlparse

SUPPORTED_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
}

MAX_FILE_SIZE_BYTES = 250 * 1024 * 1024

DEFAULT_RUBRIC = {
    "Student interaction": 0.30,
    "Rapport and engagement": 0.25,
    "Class structure": 0.20,
    "Visual and technical quality": 0.15,
    "Clarity and delivery": 0.10,
}

VALID_RATINGS = ("Excellent", "Good", "Average", "Poor")
VALID_CONFIDENCE = ("High", "Medium", "Low")


def validate_uploaded_file(file_obj, max_bytes: int = MAX_FILE_SIZE_BYTES):
    """Validate uploaded file type and size."""
    filename = getattr(file_obj, "name", "")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not filename:
        return False, "A file is required."
    if f".{extension}" not in SUPPORTED_EXTENSIONS:
        return False, f"Unsupported file type: {filename}. Supported types: {sorted(SUPPORTED_EXTENSIONS)}"
    size = getattr(file_obj, "size", 0) or 0
    if size <= 0:
        return False, "Uploaded file is empty."
    if size > max_bytes:
        return False, f"Uploaded file exceeds the {max_bytes / (1024 * 1024):.0f}MB limit."
    return True, "File accepted."


def validate_secure_url(raw_url: str):
    if not raw_url or not raw_url.strip():
        return True, "No URL provided."
    parsed = urlparse(raw_url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        return False, "Only secure http/https URLs are allowed."
    hostname = (parsed.hostname or "").lower()
    blocked_suffixes = (".local", ".internal", ".lan")
    blocked_names = {"localhost", "127.0.0.1", "::1"}
    if hostname in blocked_names or hostname.endswith(blocked_suffixes):
        return False, "Private or local network URLs are not allowed."
    return True, "URL accepted."


def rubric_configure(weights=None):
    if weights is None:
        return dict(DEFAULT_RUBRIC)
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Rubric weights must sum to a positive value.")
    normalized = {key: float(value) / total for key, value in weights.items()}
    return normalized


def gemini_permission_error(user_confirmed: bool, provider_approved: str | None = None) -> str | None:
    """Keep user consent separate from organizer approval of Google Gemini."""
    organizer_approval = (
        os.getenv("GEMINI_PROVIDER_APPROVED", "")
        if provider_approved is None
        else provider_approved
    )
    if organizer_approval.lower() != "true":
        return "Google Gemini use is disabled until the challenge organizer explicitly approves this provider."
    if not user_confirmed:
        return "Confirm that this recording may be sent to the approved Google Gemini provider before analyzing it."
    return None
