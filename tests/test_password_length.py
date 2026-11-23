"""Issue #7: reject overlong UTF-8 credentials without truncation or mutation."""

from html import unescape

import pytest

from tests.test_password_policy import _snapshot

pytestmark = pytest.mark.characterization

LONG_VALUES = [
    pytest.param("Aa1!" + "x" * 69, id="ascii-73"),
    pytest.param("Aa1!" + "é" * 35, id="utf8-74"),
    pytest.param("Aa1!" + "x" * 67 + "é", id="split-codepoint-73"),
    pytest.param("Aa1!" + "😀" * 18, id="emoji-76"),
]


@pytest.mark.parametrize("value", LONG_VALUES)
@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_overlong_signup_and_change_leave_all_rows_unchanged(
    value,
    language,
    role,
    client,
    client_factory,
    login,
    user,
    admin,
    db,
    app_modules,
    password,
):
    """Creation and authorized changes refuse long values with translated guidance."""
    signup = client_factory()
    signup.cookies.set("lang", language)
    before = _snapshot(db, app_modules.models)
    response = signup.post(
        "/register",
        data={
            "email": "length@example.com",
            "password": value,
            "confirm_password": value,
        },
    )
    assert response.status_code == 200
    assert "access_token" not in signup.cookies
    assert _snapshot(db, app_modules.models) == before
    assert (
        response.context["language"]["warning"]
        == response.context["language"]["Password-help"]
    )
    assert "72" in unescape(response.text)
    login(client, user if role == "owner" else admin)
    client.cookies.set("lang", language)
    cookie = client.cookies.get("access_token")
    response = client.post(
        f"/users/reset_password/{user.id}",
        data={
            "password": value,
            "confirm_password": value,
            **({"current_password": password} if role == "owner" else {}),
        },
    )
    assert response.status_code == 200
    assert (
        response.context["language"]["warning"]
        == response.context["language"]["Password-help"]
    )
    assert "72" in unescape(response.text)
    assert 'name="password" value=""' in response.text
    assert 'name="confirm_password" value=""' in response.text
    assert _snapshot(db, app_modules.models) == before
    assert client.cookies.get("access_token") == cookie
    login(client_factory(), user)


@pytest.mark.parametrize("value", LONG_VALUES)
@pytest.mark.parametrize("channel", ["web", "cli", "token"])
def test_overlong_authentication_never_matches_the_bcrypt_prefix(
    value,
    channel,
    client,
    client_factory,
    user,
    db,
    app_modules,
):
    """Even a matching 72-byte prefix cannot authorize a longer submitted value."""
    prefix = value.encode("utf-8")[:72].decode("utf-8", errors="ignore")
    stored_hash = app_modules.security.get_password_hash(prefix)
    user.hashed_password = stored_hash
    token = app_modules.models.Token(
        owner_id=user.id, key="length-key", secret=stored_hash
    )
    db.add(token)
    db.commit()
    before = _snapshot(db, app_modules.models)
    if channel == "token":
        response = client.post(
            "/token-signin", data={"key": token.key, "secret": value}
        )
        assert response.json() == {"Auth": "Error"}
        accepted = client_factory().post(
            "/token-signin", data={"key": token.key, "secret": prefix}
        )
        assert accepted.json().get("access_token")
    else:
        response = client.post(
            "/signin",
            data={
                "username": user.email,
                "password": value,
                "scope": "cli" if channel == "cli" else "",
            },
        )
        assert response.context["user"] is None
        lang = response.context["language"]
        assert lang["warning"] == lang["Incorrect-username-or-password"]
        accepted = client_factory().post(
            "/signin", data={"username": user.email, "password": prefix}
        )
        assert accepted.context["user"].id == user.id
    assert response.status_code == 200
    assert "access_token" not in client.cookies
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("value", LONG_VALUES)
def test_security_boundary_rejects_overlong_hash_and_verification(
    value, app_modules, password_hash
):
    """Guard the common bcrypt boundary, including internal hashing callers."""
    assert app_modules.auth.password_validity(value) is False
    assert app_modules.security.verify_password(value, password_hash) is False
    with pytest.raises(ValueError, match="72"):
        app_modules.security.get_password_hash(value)


@pytest.mark.parametrize(
    "value", ["Aa1!" + "x" * 68, "Aa1!" + "é" * 34, "Aa1!" + "😀" * 17]
)
def test_exact_72_byte_security_boundary_still_round_trips(value, app_modules):
    """Existing bcrypt hashes and ASCII/multibyte boundary inputs remain compatible."""
    assert len(value.encode("utf-8")) == 72
    encoded = app_modules.security.get_password_hash(value)
    assert app_modules.security.verify_password(value, encoded) is True
    assert app_modules.security.verify_password(value[:-1] + "z", encoded) is False
