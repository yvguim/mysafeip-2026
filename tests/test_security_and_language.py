"""Characterize current proxy-IP extraction and language selection."""

import json

import pytest
from starlette.requests import Request

pytestmark = pytest.mark.characterization


@pytest.mark.parametrize(
    "trusted,headers,peer,expected",
    [
        (
            False,
            {"x-forwarded-for": "198.51.100.1", "x-real-ip": "198.51.100.2"},
            "192.0.2.10",
            "192.0.2.10",
        ),
        (
            True,
            {"x-forwarded-for": "198.51.100.1, 192.0.2.11"},
            "192.0.2.10",
            "198.51.100.1",
        ),
        (True, {"x-forwarded-for": "2001:db8::1"}, "192.0.2.10", "2001:db8::1"),
        (
            True,
            {"x-forwarded-for": "bad", "x-real-ip": "198.51.100.2"},
            "192.0.2.10",
            "198.51.100.2",
        ),
        (True, {"x-real-ip": "bad"}, "192.0.2.10", "192.0.2.10"),
        (True, {}, "192.0.2.10", "192.0.2.10"),
        (False, {}, None, "127.0.0.1"),
    ],
)
def test_current_proxy_header_policy(
    app_modules, monkeypatch, trusted, headers, peer, expected
):
    """Current boolean trust policy is not proof that the peer is a trusted proxy."""
    monkeypatch.setattr(app_modules.settings.settings, "TRUSTED_PROXIES", trusted)
    request = Request(
        {
            "type": "http",
            "headers": [
                (key.encode(), value.encode()) for key, value in headers.items()
            ],
            "client": (peer, 50000) if peer else None,
        }
    )
    assert app_modules.security.get_client_ip(request) == expected


def test_malformed_url_is_false_instead_of_an_exception(app_modules):
    """Malformed URL parsing remains a validation rejection."""
    assert app_modules.security.is_valid_url("http://[malformed") is False


@pytest.mark.parametrize("language", ["en", "fr"])
def test_language_cookie_selects_translation(client, app_modules, language):
    """A language selection is persisted and applied on a subsequent request."""
    response = client.get(f"/lang/{language}")
    assert response.status_code == 200
    assert client.cookies["lang"] == language
    response = client.get("/")
    with (app_modules.runtime / "languages" / f"{language}.json").open(
        encoding="utf-8"
    ) as file:
        expected = json.load(file)
    assert response.context["language"] == expected


def test_unknown_language_falls_back_to_default(client, app_modules):
    """Unsupported cookie values do not select an arbitrary language file."""
    client.cookies.set("lang", "unsupported")
    response = client.get("/")
    with (app_modules.runtime / "languages" / "en.json").open(encoding="utf-8") as file:
        expected = json.load(file)
    assert response.status_code == 200
    assert response.context["language"] == expected
