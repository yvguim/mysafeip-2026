"""Narrow expected-failure exception: unrelated assertions/errors must still fail."""


class KnownBug(AssertionError):
    """Signal only the precise undesired business outcome linked to an issue."""


def expect_behavior(condition: bool, message: str) -> None:
    """Check a desired outcome separately from normal setup/precondition assertions."""
    if not condition:
        raise KnownBug(message)
