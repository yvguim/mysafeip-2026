"""Issue #6: reuse the existing signup policy for owner/admin password changes."""

from html import unescape

import pytest

pytestmark = pytest.mark.characterization

WEAK_PASSWORDS = [
    pytest.param("Aa1!b", id="five-characters"),
    pytest.param("ABC12!", id="missing-lowercase"),
    pytest.param("abc12!", id="missing-uppercase"),
    pytest.param("Abcde!", id="missing-digit"),
    pytest.param("Abcd12", id="missing-special"),
    pytest.param("abcdef", id="historical-six-lowercase"),
    pytest.param("ééA1!é", id="non-ascii-lowercase-only"),
    pytest.param("aaÉ1!a", id="non-ascii-uppercase-only"),
    pytest.param("Aa١!bc", id="non-ascii-digit-only"),
]


def _snapshot(db, models):
    """Read every persisted synthetic field, bypassing cached ORM state."""
    db.expire_all()
    return {
        model.__name__: [
            tuple(getattr(row, column.name) for column in model.__table__.columns)
            for row in db.query(model).order_by(model.id).all()
        ]
        for model in (models.User, models.Ip, models.InstantAccess, models.Token)
    }


def _assert_warning(response, key):
    """Check the real localized warning and keep submitted passwords out of inputs."""
    assert response.status_code == 200
    language = response.context["language"]
    assert language["warning"] == language[key]
    assert language[key] in unescape(response.text)
    assert 'name="password" value=""' in response.text
    assert 'name="confirm_password" value=""' in response.text


@pytest.mark.parametrize("role", ["owner", "admin"])
@pytest.mark.parametrize("language", ["fr", "en"])
@pytest.mark.parametrize("weak", WEAK_PASSWORDS)
def test_signup_and_password_change_reject_the_same_weak_values(
    role,
    language,
    weak,
    app_modules,
    db,
    user,
    admin,
    other_user,
    client,
    client_factory,
    login,
    password,
):
    """Weak replacements never change hashes, privileges, sessions or other rows."""
    assert app_modules.auth.password_validity(weak) is False
    anonymous = client_factory()
    anonymous.cookies.set("lang", language)
    before = _snapshot(db, app_modules.models)
    response = anonymous.post(
        "/register",
        data={
            "email": "weak-signup@example.com",
            "password": weak,
            "confirm_password": weak,
        },
    )
    _assert_warning(response, "Password-help")
    assert "access_token" not in anonymous.cookies
    assert _snapshot(db, app_modules.models) == before
    login(client, user if role == "owner" else admin)
    client.cookies.set("lang", language)
    original_cookie = client.cookies.get("access_token")
    response = client.post(
        f"/users/reset_password/{user.id}",
        data={
            "password": weak,
            "confirm_password": weak,
        },
    )
    assert _snapshot(db, app_modules.models) == before
    _assert_warning(response, "Password-help")
    assert response.context["user"].id == user.id
    assert client.cookies.get("access_token") == original_cookie
    probe = client_factory()
    refused = probe.post("/signin", data={"username": user.email, "password": weak})
    assert refused.status_code == 200 and refused.context["user"] is None
    assert "access_token" not in probe.cookies
    login(probe, user)
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("role", ["owner", "admin"])
@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("Aa1!bc", id="six-character-minimum"),
        pytest.param("Aa1 bc", id="space-remains-special"),
        pytest.param("Aa1!" + "x" * 68, id="ascii-72-bytes"),
        pytest.param("Aa1!" + "é" * 34, id="utf8-72-bytes"),
    ],
)
def test_valid_passwords_work_for_signup_and_authorized_change(
    role,
    replacement,
    app_modules,
    db,
    user,
    admin,
    other_user,
    client,
    client_factory,
    login,
    password,
):
    """Keep existing minimum, space and Unicode behavior up to bcrypt's byte boundary."""
    assert app_modules.auth.password_validity(replacement) is True
    assert len(replacement.encode("utf-8")) <= 72
    signup = client_factory()
    response = signup.post(
        "/register",
        data={
            "email": "valid-policy@example.com",
            "password": replacement,
            "confirm_password": replacement,
        },
    )
    assert response.status_code == 200 and "access_token" in signup.cookies
    new_user = app_modules.crud.get_user_by_email(db, "valid-policy@example.com")
    assert new_user is not None and new_user.is_admin is False
    assert new_user.hashed_password != replacement
    assert app_modules.security.verify_password(replacement, new_user.hashed_password)
    signup_probe = client_factory()
    signed_in = signup_probe.post(
        "/signin", data={"username": new_user.email, "password": replacement}
    )
    assert signed_in.status_code == 200 and "access_token" in signup_probe.cookies
    login(client, user if role == "owner" else admin)
    before = _snapshot(db, app_modules.models)
    target_before = {
        column.name: getattr(user, column.name)
        for column in app_modules.models.User.__table__.columns
    }
    response = client.post(
        f"/users/reset_password/{user.id}",
        data={
            "password": replacement,
            "confirm_password": replacement,
        },
    )
    assert response.status_code == 200
    language = response.context["language"]
    assert language["success"] == language["Password-reset-successfull"]
    assert language["success"] in unescape(response.text)
    assert 'name="password" value=""' in response.text
    assert 'name="confirm_password" value=""' in response.text
    after = _snapshot(db, app_modules.models)
    saved = db.get(app_modules.models.User, user.id)
    assert saved.hashed_password != target_before["hashed_password"]
    assert saved.hashed_password != replacement
    assert app_modules.security.verify_password(replacement, saved.hashed_password)
    for name, old_value in target_before.items():
        if name != "hashed_password":
            assert getattr(saved, name) == old_value
    assert [row for row in before["User"] if row[0] != user.id] == [
        row for row in after["User"] if row[0] != user.id
    ]
    for name in ("Ip", "InstantAccess", "Token"):
        assert after[name] == before[name]
    old_probe = client_factory()
    rejected = old_probe.post(
        "/signin", data={"username": user.email, "password": password}
    )
    assert rejected.status_code == 200 and rejected.context["user"] is None
    assert "access_token" not in old_probe.cookies
    accepted = old_probe.post(
        "/signin", data={"username": user.email, "password": replacement}
    )
    assert accepted.status_code == 200 and "access_token" in old_probe.cookies


@pytest.mark.parametrize("role", ["owner", "admin"])
@pytest.mark.parametrize("language", ["fr", "en"])
def test_confirmation_mismatch_still_rejects_valid_password_without_mutation(
    role,
    language,
    client,
    client_factory,
    login,
    user,
    admin,
    db,
    app_modules,
):
    """Policy compliance cannot bypass confirmation in either form."""
    fields = {"password": "Changed-pass-43!", "confirm_password": "Different-pass-44!"}
    assert all(app_modules.auth.password_validity(value) for value in fields.values())
    anonymous = client_factory()
    anonymous.cookies.set("lang", language)
    before = _snapshot(db, app_modules.models)
    response = anonymous.post(
        "/register", data={"email": "confirmation@example.com", **fields}
    )
    _assert_warning(response, "Password-missmatch")
    assert "access_token" not in anonymous.cookies
    assert _snapshot(db, app_modules.models) == before
    login(client, user if role == "owner" else admin)
    client.cookies.set("lang", language)
    response = client.post(f"/users/reset_password/{user.id}", data=fields)
    _assert_warning(response, "Password-missmatch")
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("replacement", ["abcdef", "Changed-pass-43!"])
@pytest.mark.parametrize("language", ["fr", "en"])
def test_peer_password_change_is_denied_before_policy_validation(
    replacement,
    language,
    client,
    login,
    user,
    other_user,
    db,
    app_modules,
):
    """A valid or weak replacement grants no access to someone else's account."""
    login(client, user)
    client.cookies.set("lang", language)
    before = _snapshot(db, app_modules.models)
    response = client.post(
        f"/users/reset_password/{other_user.id}",
        data={
            "password": replacement,
            "confirm_password": replacement,
        },
    )
    assert response.status_code == 200
    assert response.context["user"] is False
    lang = response.context["language"]
    assert lang["danger"] == lang["You-are-not-allowed-to-do-this"]
    assert lang["danger"] in unescape(response.text)
    assert not lang.get("warning")
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("replacement", ["abcdef", "Changed-pass-43!"])
def test_anonymous_password_change_remains_unauthenticated(
    replacement, client, user, db, app_modules
):
    """No password policy path can bypass authentication."""
    before = _snapshot(db, app_modules.models)
    response = client.post(
        f"/users/reset_password/{user.id}",
        data={
            "password": replacement,
            "confirm_password": replacement,
        },
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert _snapshot(db, app_modules.models) == before
