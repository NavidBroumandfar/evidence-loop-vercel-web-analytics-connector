"""Custom exceptions with fixed error codes and messages."""


class ConnectorError(Exception):
    """Base exception for connector errors."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ValidationError(ConnectorError):
    """Input validation failed."""

    pass


class ProviderUnavailableError(ConnectorError):
    """Provider service unavailable or inaccessible."""

    pass


class PartialResponseError(ConnectorError):
    """Provider response missing required metrics."""

    pass


class SecurityError(ConnectorError):
    """Security boundary violation."""

    pass


class TransportError(ConnectorError):
    """HTTP transport failure."""

    pass
