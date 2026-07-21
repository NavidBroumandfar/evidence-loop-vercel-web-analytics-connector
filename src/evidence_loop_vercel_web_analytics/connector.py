"""Vercel Web Analytics visits/count connector."""

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from .errors import (
    PartialResponseError,
    ProviderUnavailableError,
    SecurityError,
    TransportError,
    ValidationError,
)
from .http import (
    API_URL,
    MAX_RESPONSE_SIZE,
    Transport,
    UrllibTransport,
    check_nesting_depth,
    parse_response,
)
from .safety import (
    serialize_envelope,
    validate_now,
    validate_project_id,
    validate_scope_ref,
    validate_site_id,
    validate_site_url,
    validate_stale_threshold,
    validate_team_id,
    validate_token,
    validate_window,
)


DEFAULT_STALE_THRESHOLD_HOURS = 24


def collect(
    site_url: str,
    site_id: str,
    scope_ref: str,
    since: str,
    until: str,
    stale_threshold_hours: int = DEFAULT_STALE_THRESHOLD_HOURS,
    transport: Transport | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect visits/count data and produce envelope."""
    canonical_site_url = validate_site_url(site_url)
    validate_site_id(site_id)
    validate_scope_ref(scope_ref)

    # Create exactly one collection_time at function entry
    if now is not None:
        collection_time = validate_now(now)
    else:
        collection_time = datetime.now(timezone.utc).replace(microsecond=0)

    since_dt, until_dt = validate_window(since, until, collection_time)
    validate_stale_threshold(stale_threshold_hours)

    project_id = os.environ.get("VERCEL_PROJECT_ID")
    token = os.environ.get("VERCEL_TOKEN")
    team_id = os.environ.get("VERCEL_TEAM_ID")
    bound_site_url = os.environ.get("VERCEL_SITE_URL")

    if not project_id:
        raise ValidationError("MISSING_PROJECT_ID", "VERCEL_PROJECT_ID not set")
    if not token:
        raise ValidationError("MISSING_TOKEN", "VERCEL_TOKEN not set")
    if not bound_site_url:
        raise ValidationError("MISSING_SITE_BINDING", "VERCEL_SITE_URL not set")

    validate_project_id(project_id)
    validate_token(token)
    if team_id:
        validate_team_id(team_id)
    if validate_site_url(bound_site_url) != canonical_site_url:
        raise ValidationError("SITE_BINDING_MISMATCH", "Configured site binding does not match site URL")

    if transport is None:
        transport = UrllibTransport()

    params = {
        "projectId": project_id,
        "since": since,
        "until": until,
    }
    if team_id:
        params["teamId"] = team_id

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "evidence-loop-vercel-web-analytics-connector/0.1.0",
    }

    response = transport.get(API_URL, headers, params)

    # Validate the body type before inspecting its length.  This preserves a
    # structured transport error for malformed fake/provider responses while
    # retaining the provider-unavailable category for oversized byte bodies.
    if not isinstance(response.body, bytes):
        raise TransportError("INVALID_BODY", "Response body must be bytes")
    if len(response.body) > MAX_RESPONSE_SIZE:
        raise ProviderUnavailableError("RESPONSE_TOO_LARGE", "Response exceeds size limit")

    data = parse_response(response)
    check_nesting_depth(data)

    _validate_response_structure(data, since, until)

    response_sha256 = hashlib.sha256(response.body).hexdigest()

    # Use the same collection_time for collected_at and freshness
    collected_at_str = collection_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    hours_since_until = (collection_time - until_dt).total_seconds() / 3600
    freshness = "stale" if hours_since_until > stale_threshold_hours else "fresh"

    envelope = {
        "collected_at": collected_at_str,
        "completeness": "complete",
        "freshness": freshness,
        "grain": "site-level",
        "limitations": "Vercel Web Analytics visits/count endpoint. Metrics represent aggregated counts for the specified operator-bound project, site, and time window.",
        "lineage": [
            {
                "stage": "provider-response",
                "reference": "provider_response_sha256",
                "method": "sha256",
            }
        ],
        "measures": {
            "pageviews": {
                "unit": "count",
                "value": data["data"]["pageviews"],
            },
            "visitors": {
                "unit": "count",
                "value": data["data"]["visitors"],
            },
        },
        "observation_window": {
            "start": since,
            "end": until,
        },
        "provider": "vercel-web-analytics",
        "provider_response_sha256": response_sha256,
        "schema_version": "1",
        "scope_ref": scope_ref,
        "site_id": site_id,
        "site_url": canonical_site_url,
        "source": "evidence-loop-vercel-web-analytics",
        "uncertainty": "low",
    }

    # Check every credential value independently.  Substring overlap is
    # intentional: a public field containing any complete secret is rejected,
    # including short synthetic-looking project/team identifiers.
    sensitive_values = [token, project_id]
    if team_id is not None:
        sensitive_values.append(team_id)

    serialize_envelope(envelope, sensitive_values)

    return envelope


def _validate_response_structure(data: dict, since: str, until: str) -> None:
    """Validate response matches expected structure."""
    if not isinstance(data, dict):
        raise ProviderUnavailableError("INVALID_RESPONSE", "Response must be object")

    required_keys = {"version", "query", "data"}
    if set(data.keys()) != required_keys:
        raise ProviderUnavailableError("INVALID_RESPONSE_KEYS", "Invalid response structure")

    version = data["version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProviderUnavailableError("INVALID_VERSION", "Response version must be integer")
    if version != 1:
        raise ProviderUnavailableError("INVALID_VERSION", "Response version must be 1")

    query = data["query"]
    if not isinstance(query, dict):
        raise ProviderUnavailableError("INVALID_QUERY", "Query must be object")

    expected_query_keys = {"since", "until"}
    if set(query.keys()) != expected_query_keys:
        raise ProviderUnavailableError("INVALID_QUERY", "Query must contain exactly since and until")

    if not _matches_provider_timestamp_echo(query.get("since"), since):
        raise ProviderUnavailableError("QUERY_MISMATCH", "Since echo mismatch")
    if not _matches_provider_timestamp_echo(query.get("until"), until):
        raise ProviderUnavailableError("QUERY_MISMATCH", "Until echo mismatch")

    metrics = data["data"]
    if not isinstance(metrics, dict):
        raise ProviderUnavailableError("INVALID_DATA", "Data must be object")

    required_metrics = {"pageviews", "visitors"}
    metric_keys = set(metrics.keys())

    if metric_keys == required_metrics:
        pass
    elif metric_keys < required_metrics:
        raise PartialResponseError("MISSING_METRICS", "Response missing required metrics")
    else:
        raise ProviderUnavailableError("INVALID_DATA", "Data contains unexpected keys")

    for key in ("pageviews", "visitors"):
        value = metrics[key]
        if isinstance(value, bool):
            raise ProviderUnavailableError("INVALID_METRIC_TYPE", f"{key} must not be boolean")
        if not isinstance(value, int):
            raise ProviderUnavailableError("INVALID_METRIC_TYPE", f"{key} must be integer")
        if value < 0:
            raise ProviderUnavailableError("INVALID_METRIC_VALUE", f"{key} must be non-negative")
        if value > 9007199254740991:
            raise ProviderUnavailableError("INVALID_METRIC_VALUE", f"{key} exceeds safe integer limit")


def _matches_provider_timestamp_echo(value: Any, expected: str) -> bool:
    """Accept only Vercel's two observed canonical UTC echo forms."""

    if not isinstance(value, str):
        return False
    return value == expected or value == f"{expected[:-1]}.000Z"
