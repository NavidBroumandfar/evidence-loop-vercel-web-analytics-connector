"""Safety validation and sanitization."""

import ipaddress
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from .errors import SecurityError, ValidationError

MAX_WINDOW_DAYS = 31


def validate_site_url(site_url: str) -> str:
    """Validate and canonicalize HTTPS DNS origin."""
    if not isinstance(site_url, str) or not site_url:
        raise ValidationError("INVALID_SITE_URL", "Invalid site URL")

    # Reject all whitespace, Unicode control/format characters, and backslashes
    # before parsing.  URL parsers otherwise normalize some of these values in
    # ways that can change the effective host or path.
    if any(char.isspace() or unicodedata.category(char) in {"Cc", "Cf"} for char in site_url):
        raise ValidationError("INVALID_SITE_URL", "Whitespace or control characters not allowed")
    if "\\" in site_url:
        raise ValidationError("INVALID_SITE_URL", "Backslashes not allowed")

    site_url = site_url.lower()

    if not site_url.startswith("https://"):
        raise ValidationError("INVALID_SITE_URL", "Must be HTTPS")

    # Check for double-slash paths
    if "//" in site_url[8:]:  # After "https://"
        raise ValidationError("INVALID_SITE_URL", "Double-slash paths not allowed")

    try:
        parsed = urlparse(site_url)
    except ValueError:
        raise ValidationError("INVALID_SITE_URL", "Invalid URL")

    if parsed.username or parsed.password:
        raise ValidationError("INVALID_SITE_URL", "Userinfo not allowed")

    try:
        port = parsed.port
    except (ValueError, TypeError):
        raise ValidationError("INVALID_SITE_URL", "Invalid port")

    if port is not None:
        raise ValidationError("INVALID_SITE_URL", "Explicit port not allowed")

    path = parsed.path
    if path and path != "/":
        raise ValidationError("INVALID_SITE_URL", "Path must be root only")

    if parsed.query or parsed.fragment:
        raise ValidationError("INVALID_SITE_URL", "Query and fragment not allowed")

    try:
        hostname = parsed.hostname
    except ValueError:
        raise ValidationError("INVALID_SITE_URL", "Invalid hostname")
    if not hostname:
        raise ValidationError("INVALID_SITE_URL", "Missing hostname")

    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValidationError("INVALID_SITE_URL", "Localhost not allowed")

    try:
        ipaddress.ip_address(hostname)
        raise ValidationError("INVALID_SITE_URL", "IP address not allowed")
    except ValueError:
        pass

    if len(hostname) > 253:
        raise ValidationError("INVALID_SITE_URL", "Hostname too long")

    labels = hostname.split(".")
    if len(labels) < 2:
        raise ValidationError("INVALID_SITE_URL", "Invalid hostname")

    for label in labels:
        if len(label) == 0 or len(label) > 63:
            raise ValidationError("INVALID_SITE_URL", "Invalid hostname label")
        if not re.match(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$", label):
            raise ValidationError("INVALID_SITE_URL", "Invalid hostname label")

    return f"https://{hostname}"


def validate_site_id(site_id: str) -> str:
    """Validate site_id: lowercase alphanumeric + hyphen, max 63."""
    if not isinstance(site_id, str):
        raise ValidationError("INVALID_SITE_ID", "Must be string")
    if not site_id or len(site_id) > 63:
        raise ValidationError("INVALID_SITE_ID", "Invalid length")

    if not re.match(r"^[a-z0-9][a-z0-9\-]{0,62}$", site_id):
        raise ValidationError("INVALID_SITE_ID", "Invalid format")

    if site_id.endswith("-"):
        raise ValidationError("INVALID_SITE_ID", "Cannot end with hyphen")

    return site_id


def validate_scope_ref(scope_ref: str) -> str:
    """Validate scope_ref as a bounded, non-path public identifier."""
    if not isinstance(scope_ref, str):
        raise ValidationError("INVALID_SCOPE_REF", "Must be string")
    if not scope_ref or len(scope_ref) > 128:
        raise ValidationError("INVALID_SCOPE_REF", "Invalid length")

    # Scope references are public aliases, never filesystem or URL paths.
    # A single dot may be meaningful in an alias, but dot-dot and path
    # separators are rejected explicitly.
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", scope_ref) or ".." in scope_ref:
        raise ValidationError("INVALID_SCOPE_REF", "Invalid characters")

    return scope_ref


def validate_timestamp(ts: str, name: str) -> datetime:
    """Validate canonical UTC ISO-8601 Z timestamp."""
    if not isinstance(ts, str):
        raise ValidationError(f"INVALID_{name.upper()}", "Must be string")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts):
        raise ValidationError(f"INVALID_{name.upper()}", "Must be YYYY-MM-DDTHH:MM:SSZ")

    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(f"INVALID_{name.upper()}", "Invalid timestamp")

    return dt


def validate_now(now: datetime) -> datetime:
    """Validate and normalize now parameter to whole-second UTC."""
    if not isinstance(now, datetime):
        raise ValidationError("INVALID_NOW", "Must be datetime")

    if now.tzinfo is None:
        raise ValidationError("INVALID_NOW", "Must be timezone-aware")

    if now.utcoffset().total_seconds() != 0:
        raise ValidationError("INVALID_NOW", "Must be UTC")

    return now.replace(microsecond=0)


def validate_window(since: str, until: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Validate bounded UTC window."""
    since_dt = validate_timestamp(since, "since")
    until_dt = validate_timestamp(until, "until")

    if until_dt <= since_dt:
        raise ValidationError("INVALID_WINDOW", "Until must be after since")

    if until_dt - since_dt > timedelta(days=MAX_WINDOW_DAYS):
        raise ValidationError("INVALID_WINDOW", "Window cannot exceed 31 days")

    if now is None:
        current_time = datetime.now(timezone.utc).replace(microsecond=0)
    else:
        current_time = validate_now(now)

    if until_dt > current_time:
        raise ValidationError("INVALID_WINDOW", "Until cannot be in the future")

    return since_dt, until_dt


def validate_token(token: str) -> None:
    """Validate token: bounded non-whitespace opaque text."""
    if not isinstance(token, str):
        raise ValidationError("INVALID_TOKEN", "Must be string")
    if not token or len(token) > 512:
        raise ValidationError("INVALID_TOKEN", "Invalid token length")

    if not re.match(r"^[^\s]+$", token):
        raise ValidationError("INVALID_TOKEN", "Token contains whitespace")


def validate_project_id(project_id: str) -> None:
    """Validate project ID: strict prj_ plus bounded alphanumeric."""
    if not isinstance(project_id, str):
        raise ValidationError("INVALID_PROJECT_ID", "Must be string")
    if not re.fullmatch(r"prj_[a-zA-Z0-9]{1,64}", project_id):
        raise ValidationError("INVALID_PROJECT_ID", "Invalid project ID format")


def validate_team_id(team_id: str) -> None:
    """Validate team ID: strict team_ plus bounded alphanumeric."""
    if not isinstance(team_id, str):
        raise ValidationError("INVALID_TEAM_ID", "Must be string")
    if not re.fullmatch(r"team_[a-zA-Z0-9]{1,64}", team_id):
        raise ValidationError("INVALID_TEAM_ID", "Invalid team ID format")


def validate_stale_threshold(hours: int) -> None:
    """Validate stale threshold as nonnegative integer."""
    if isinstance(hours, bool):
        raise ValidationError("INVALID_STALE_THRESHOLD", "Must be integer, not boolean")

    if not isinstance(hours, int):
        raise ValidationError("INVALID_STALE_THRESHOLD", "Must be integer")

    if hours < 0:
        raise ValidationError("INVALID_STALE_THRESHOLD", "Must be non-negative")


def check_credential_leakage(text: str, sensitive_values: list[str] | None = None) -> None:
    """Detect credential patterns and sensitive value overlap in output."""
    if sensitive_values:
        for value in sensitive_values:
            if value and value in text:
                raise SecurityError("CREDENTIAL_LEAK", "Sensitive value detected in output")

    patterns = [
        r"Bearer\s+[A-Za-z0-9\-._~+/]{32,}",
        r"token\s*=\s*['\"][A-Za-z0-9\-._~+/]{32,}['\"]",
        r"prj_[a-zA-Z0-9]{24,}",
        r"team_[a-zA-Z0-9]{24,}",
        r"VERCEL_TOKEN\s*=\s*['\"][^'\"]{8,}['\"]",
        r"VERCEL_PROJECT_ID\s*=\s*['\"]prj_[a-zA-Z0-9]{20,}['\"]",
        r"VERCEL_TEAM_ID\s*=\s*['\"]team_[a-zA-Z0-9]{20,}['\"]",
        r"secret[_-]?key\s*=\s*['\"][^'\"]{8,}['\"]",
        r"private[_-]?key\s*=\s*['\"][^'\"]{8,}['\"]",
    ]

    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            raise SecurityError("CREDENTIAL_LEAK", "Credential pattern detected in output")


def serialize_envelope(envelope: dict, sensitive_values: list[str] | None = None) -> str:
    """Serialize envelope as compact sorted UTF-8 JSON with newline, with sanitization."""
    json_str = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    output = json_str + "\n"

    if len(output.encode("utf-8")) > 1024 * 1024:
        raise SecurityError("OUTPUT_TOO_LARGE", "Serialized output exceeds 1 MiB")

    check_credential_leakage(output, sensitive_values)

    return output
