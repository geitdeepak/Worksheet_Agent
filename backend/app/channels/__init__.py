class TransientError(Exception):
    """Worth retrying: provider outage, timeout, throttling."""


class PermanentError(Exception):
    """Retrying will not help: invalid recipient, rejected content, bad configuration."""
