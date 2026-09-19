"""Core exception hierarchy for XAUUSD Quantitative Platform."""


class XAUQuantError(Exception):
    """Base exception for all XAU platform errors."""


class ConfigurationError(XAUQuantError):
    """Raised when configuration loading, substitution, or validation fails."""


class EnvironmentIntegrityError(XAUQuantError):
    """Raised when runtime environment, directory, or dependency integrity check fails."""


class PathResolutionError(XAUQuantError):
    """Raised when deterministic path resolution fails or resolves outside project root."""


class LoggingError(XAUQuantError):
    """Raised when logging setup or log sink initialization fails."""
