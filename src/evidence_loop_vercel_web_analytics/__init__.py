"""Evidence Loop Vercel Web Analytics Connector."""

from .connector import collect
from .errors import (
    ConnectorError,
    PartialResponseError,
    ProviderUnavailableError,
    SecurityError,
    TransportError,
    ValidationError,
)
from .http import HTTPResponse, Transport

__version__ = "0.1.0"

__all__ = [
    "collect",
    "ConnectorError",
    "ValidationError",
    "ProviderUnavailableError",
    "PartialResponseError",
    "SecurityError",
    "TransportError",
    "Transport",
    "HTTPResponse",
    "__version__",
]
