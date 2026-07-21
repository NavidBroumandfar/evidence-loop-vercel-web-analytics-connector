"""HTTP transport with strict security constraints."""

import json
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .errors import ProviderUnavailableError, TransportError


API_ORIGIN = "https://api.vercel.com"
API_PATH = "/v1/query/web-analytics/visits/count"
API_URL = f"{API_ORIGIN}{API_PATH}"

MAX_RESPONSE_SIZE = 1024 * 1024
USER_AGENT = "evidence-loop-vercel-web-analytics-connector/0.1.0"


@dataclass(frozen=True)
class HTTPResponse:
    """Immutable HTTP response."""

    status: int
    headers: dict[str, str]
    body: bytes


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Handler that refuses to follow redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Return None to prevent redirect."""
        return None


class Transport(ABC):
    """Abstract transport interface."""

    @abstractmethod
    def get(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> HTTPResponse:
        """Execute GET request."""
        pass


class UrllibTransport(Transport):
    """Real urllib transport pinned to exact endpoint."""

    def __init__(self):
        """Initialize with no-redirect opener."""
        self.opener = urllib.request.build_opener(NoRedirectHandler())

    def get(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> HTTPResponse:
        if url != API_URL:
            raise TransportError("WRONG_URL", "Invalid endpoint")

        allowed_headers = {"Authorization", "Accept", "User-Agent"}
        for key in headers:
            if key not in allowed_headers:
                raise TransportError("INVALID_HEADER", "Invalid request header")

        if "User-Agent" not in headers:
            headers["User-Agent"] = USER_AGENT

        query_string = urllib.parse.urlencode(params, doseq=True)
        full_url = f"{url}?{query_string}"

        req = urllib.request.Request(full_url, method="GET")
        for key, value in headers.items():
            req.add_header(key, value)

        try:
            with self.opener.open(req, timeout=30) as response:
                status = response.status
                resp_headers = dict(response.headers)
                body = response.read(MAX_RESPONSE_SIZE + 1)

            if len(body) > MAX_RESPONSE_SIZE:
                raise TransportError("RESPONSE_TOO_LARGE", "Response exceeds size limit")

            if 300 <= status < 400:
                raise ProviderUnavailableError("REDIRECT_REFUSED", "Redirects not allowed")

            return HTTPResponse(status=status, headers=resp_headers, body=body)

        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                raise ProviderUnavailableError("REDIRECT_REFUSED", "Redirects not allowed")
            raise ProviderUnavailableError("HTTP_ERROR", "HTTP request failed")
        except urllib.error.URLError:
            raise ProviderUnavailableError("NETWORK_ERROR", "Network request failed")


def parse_response(response: HTTPResponse) -> dict:
    """Parse and validate JSON response."""
    if not isinstance(response.body, bytes):
        raise TransportError("INVALID_BODY", "Response body must be bytes")

    if len(response.body) > MAX_RESPONSE_SIZE:
        raise TransportError("RESPONSE_TOO_LARGE", "Response exceeds size limit")

    # Validate status is non-bool integer
    if isinstance(response.status, bool) or not isinstance(response.status, int):
        raise TransportError("INVALID_STATUS", "Response status must be integer")

    if response.status != 200:
        raise ProviderUnavailableError("NON_200_STATUS", "Invalid response status")

    if not isinstance(response.headers, dict):
        raise TransportError("INVALID_HEADERS", "Response headers must be dict")

    # Header names and values are treated case-insensitively, but malformed
    # non-string entries fail closed instead of leaking an AttributeError.
    headers_lower: dict[str, str] = {}
    for key, value in response.headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TransportError("INVALID_HEADERS", "Response headers must contain strings")
        headers_lower[key.lower()] = value

    content_type = headers_lower.get("content-type", "").lower().split(";", 1)[0].strip()
    if content_type != "application/json":
        raise TransportError("INVALID_CONTENT_TYPE", "Invalid response type")

    try:
        text = response.body.decode("utf-8")
    except UnicodeDecodeError:
        raise TransportError("INVALID_UTF8", "Invalid response encoding")

    try:
        data = json.loads(text, object_pairs_hook=_check_duplicate_keys)
    except json.JSONDecodeError:
        raise TransportError("INVALID_JSON", "Invalid response format")

    return data


def _check_duplicate_keys(pairs):
    """Reject duplicate JSON keys."""
    keys = set()
    for key, value in pairs:
        if key in keys:
            raise json.JSONDecodeError("Duplicate key detected", "", 0)
        keys.add(key)
    return dict(pairs)


def check_nesting_depth(obj, max_depth=10, current_depth=0):
    """Reject excessive nesting."""
    if current_depth > max_depth:
        raise TransportError("EXCESSIVE_NESTING", "Response too deeply nested")

    if isinstance(obj, dict):
        for value in obj.values():
            check_nesting_depth(value, max_depth, current_depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            check_nesting_depth(item, max_depth, current_depth + 1)
