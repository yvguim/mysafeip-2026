"""Shared TTL policy for user-submitted form durations."""

MAX_TTL_HOURS = 720


class InvalidTTLType(ValueError):
    """Reject unsupported input types without breaking callers catching ValueError."""


def validate_ttl_hours(value: str | int) -> int:
    """Return whole hours in the owner-approved inclusive range of 1 to 720."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InvalidTTLType("Invalid TTL duration")
    hours = int(value)
    if not 1 <= hours <= MAX_TTL_HOURS:
        raise ValueError("Invalid TTL duration")
    return hours
