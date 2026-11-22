import logging

import pytest


@pytest.mark.parametrize("configured", [None, "", "  "])
def test_missing_secret_is_random_and_not_logged(
    app_modules, monkeypatch, caplog, configured
):
    if configured is None:
        monkeypatch.delenv("JWT_SECRET")
    else:
        monkeypatch.setenv("JWT_SECRET", configured)

    with caplog.at_level(logging.WARNING):
        first = app_modules.settings.Settings().JWT_SECRET
        second = app_modules.settings.Settings().JWT_SECRET

    assert len(first) >= 64 and len(second) >= 64 and first != second
    assert any("Configure JWT_SECRET" in message for message in caplog.messages)
    assert first not in caplog.text and second not in caplog.text


def test_configured_secret_is_preserved_without_warning(
    app_modules, monkeypatch, caplog
):
    configured = "synthetic-configured-value-for-test-only"
    monkeypatch.setenv("JWT_SECRET", configured)

    with caplog.at_level(logging.WARNING):
        assert app_modules.settings.Settings().JWT_SECRET == configured
        assert app_modules.settings.Settings().JWT_SECRET == configured

    assert not caplog.messages
