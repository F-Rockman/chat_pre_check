class PrecheckError(Exception):
    """Base error class for the pre-check engine."""


class PolicyBlockedError(PrecheckError):
    """Raised when policy rules block request processing."""


class DataUnavailableError(PrecheckError):
    """Raised when a required upstream dependency is unavailable."""


class ResolverUnavailableError(DataUnavailableError):
    """Raised when entity resolver cannot serve requests."""
