"""Regression coverage for account settings that must not implicitly change TOTP."""

from html.parser import HTMLParser

import pytest


class _FormInputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.forms.append([])
        elif tag == "input" and self.forms:
            self.forms[-1].append(attrs)


pytestmark = pytest.mark.characterization
SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def _snapshot(db, models):
    db.expire_all()
    return {
        model.__name__: {
            row.id: {
                column.name: getattr(row, column.name)
                for column in model.__table__.columns
            }
            for row in db.query(model).order_by(model.id)
        }
        for model in (models.User, models.Token, models.Ip, models.InstantAccess)
    }


@pytest.mark.parametrize(
    "operation", ["ip-ttl", "ia-ttl", "both-ttls", "token", "noop", "delete"]
)
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("role", ["owner", "admin-selected"])
@pytest.mark.parametrize("transport", ["cookie", "bearer"])
def test_unrelated_settings_preserve_totp_and_only_apply_requested_changes(
    operation,
    enabled,
    role,
    transport,
    client,
    user,
    other_user,
    admin,
    login,
    db,
    app_modules,
    password,
):
    """Partial settings requests preserve both active and inactive TOTP and unrelated rows."""
    models = app_modules.models
    actor = user if role == "owner" else admin
    headers = {}
    if transport == "cookie":
        login(client, actor)
    else:
        signed_in = client.post(
            "/signin",
            data={
                "username": actor.email,
                "password": password,
                "scope": "cli",
            },
        )
        assert signed_in.status_code == 200
        headers["Authorization"] = f"Bearer {signed_in.json()['access_token']}"
        assert "access_token" not in client.cookies
    original_cookie = client.cookies.get("access_token")
    user.twofactor = SECRET if enabled else ""
    other_user.twofactor = SECRET
    db.add(
        models.Token(owner_id=user.id, key="existing-key", secret=user.hashed_password)
    )
    db.add(
        models.Token(
            owner_id=other_user.id, key="other-key", secret=other_user.hashed_password
        )
    )
    db.add(models.Ip(owner_id=user.id, value="192.0.2.42", origin="manual"))
    db.add(
        models.InstantAccess(
            owner_id=user.id, unique_link="settings-link", link="https://example.com"
        )
    )
    db.commit()
    token_id = db.query(models.Token).filter_by(owner_id=user.id).one().id
    data = {
        "ip-ttl": {"ip_default_ttl_hours": "6"},
        "ia-ttl": {"ia_default_ttl_hours": "48"},
        "both-ttls": {"ip_default_ttl_hours": "6", "ia_default_ttl_hours": "48"},
        "token": {"token": "true", "description": "generated safely"},
        "noop": {},
        "delete": {"action": "delete", "token_id": str(token_id)},
    }[operation]
    before = _snapshot(db, models)
    response = client.post(f"/users/details/{user.id}", data=data, headers=headers)
    if operation == "delete" and role == "admin-selected":
        assert response.status_code == 404
        assert _snapshot(db, models) == before
        return
    assert response.status_code == 200
    assert response.context["twofactorurl"] == ""
    assert "otpauth://" not in response.text
    assert "set-cookie" not in response.headers
    assert client.cookies.get("access_token") == (
        original_cookie if transport == "cookie" else None
    )
    after = _snapshot(db, models)
    expected = before
    if operation in ("ip-ttl", "both-ttls"):
        expected["User"][user.id]["ip_default_ttl_hours"] = 6
    if operation in ("ia-ttl", "both-ttls"):
        expected["User"][user.id]["ia_default_ttl_hours"] = 48
    if operation == "token":
        issued = response.context["newtoken"]
        additions = set(after["Token"]) - set(before["Token"])
        assert len(additions) == 1
        added_id = additions.pop()
        added = after["Token"][added_id]
        assert added["owner_id"] == user.id
        assert added["key"] == issued["key"]
        assert added["description"] == "generated safely"
        assert app_modules.security.verify_password(issued["secret"], added["secret"])
        expected["Token"][added_id] = added
    elif operation == "delete":
        del expected["Token"][token_id]
    assert after == expected


@pytest.mark.parametrize("operation", ["ttl", "token"])
def test_preserved_totp_still_requires_valid_code_for_new_login(
    operation,
    client,
    client_factory,
    user,
    login,
    db,
    app_modules,
    password,
    totp_time,
):
    """Unrelated writes must not turn password-only authentication into a successful login."""
    import pyotp

    user.twofactor = SECRET
    db.commit()
    code = pyotp.TOTP(SECRET).at(totp_time)
    login(client, user, two_factor_code=code)
    data = {"ip_default_ttl_hours": "6"} if operation == "ttl" else {"token": "true"}
    response = client.post(f"/users/details/{user.id}", data=data)
    assert response.status_code == 200
    db.expire_all()
    assert db.get(app_modules.models.User, user.id).twofactor == SECRET
    for submitted in ({}, {"two_factor_code": "invalid"}):
        fresh = client_factory()
        refused = fresh.post(
            "/signin", data={"username": user.email, "password": password, **submitted}
        )
        assert refused.status_code == 200
        assert refused.context["user"] is None
        assert "access_token" not in fresh.cookies
    fresh = client_factory()
    login(client=fresh, user=user, two_factor_code=code)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "data,expected",
    [
        ({"twofactor": ""}, "keep"),
        ({"twofactor": "false"}, "keep"),
        ({"twofactor": "unexpected"}, "keep"),
        ({"twofactor_settings": "false"}, "keep"),
        ({"twofactor_settings": "true"}, "disabled"),
        ({"twofactor_settings": "true", "twofactor": ""}, "disabled"),
        ({"twofactor_settings": "true", "twofactor": "false"}, "keep"),
        ({"twofactor": "true"}, "enabled"),
        ({"twofactor_settings": "true", "twofactor": "true"}, "enabled"),
    ],
)
def test_totp_changes_require_explicit_form_intent(
    enabled,
    data,
    expected,
    client,
    user,
    login,
    db,
    app_modules,
):
    """Omitted/empty/unknown values do not stand for deliberate checkbox deactivation."""
    login(client, user)
    user.twofactor = SECRET if enabled else ""
    db.commit()
    before = _snapshot(db, app_modules.models)
    response = client.post(f"/users/details/{user.id}", data=data)
    assert response.status_code == 200
    after = _snapshot(db, app_modules.models)
    old_secret = before["User"][user.id]["twofactor"]
    saved = after["User"][user.id]["twofactor"]
    if expected == "keep" or (expected == "enabled" and enabled):
        assert saved == old_secret
        assert response.context["twofactorurl"] == ""
    elif expected == "disabled":
        assert saved == ""
        assert response.context["twofactorurl"] == ""
    else:
        assert len(saved) == 32
        assert response.context["twofactorurl"].startswith("otpauth://totp/")
    before["User"][user.id]["twofactor"] = saved
    assert after == before


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("twofactor", ["", "true"])
def test_token_deletion_never_changes_totp_even_with_settings_fields(
    enabled,
    twofactor,
    client,
    user,
    login,
    db,
    app_modules,
):
    login(client, user)
    user.twofactor = SECRET if enabled else ""
    token = app_modules.models.Token(
        owner_id=user.id, key="delete-key", secret=user.hashed_password
    )
    db.add(token)
    db.commit()
    token_id = token.id
    before = _snapshot(db, app_modules.models)
    response = client.post(
        f"/users/details/{user.id}",
        data={
            "action": "delete",
            "token_id": str(token_id),
            "twofactor_settings": "true",
            "twofactor": twofactor,
        },
    )
    assert response.status_code == 200
    assert response.context["twofactorurl"] == ""
    after = _snapshot(db, app_modules.models)
    del before["Token"][token_id]
    assert after == before


@pytest.mark.parametrize("role", ["owner", "admin-selected"])
@pytest.mark.parametrize("language", ["en", "fr"])
def test_rendered_checkbox_form_explicitly_disables_and_reenables_totp(
    role,
    language,
    client,
    user,
    admin,
    login,
    db,
    app_modules,
):
    """The rendered form works without JS; token-delete forms do not carry TOTP intent."""
    login(client, user if role == "owner" else admin)
    client.cookies.set("lang", language)
    user.twofactor = SECRET
    db.add(
        app_modules.models.Token(
            owner_id=user.id, key="visible-key", secret=user.hashed_password
        )
    )
    db.commit()
    page = client.get(f"/users/details/{user.id}")
    parser = _FormInputs()
    parser.feed(page.text)
    settings = next(
        form
        for form in parser.forms
        if any(item.get("name") == "twofactor" for item in form)
    )
    marker = next(
        (item for item in settings if item.get("name") == "twofactor_settings"), None
    )
    assert marker == {"type": "hidden", "name": "twofactor_settings", "value": "true"}
    checkbox = next(item for item in settings if item.get("name") == "twofactor")
    assert checkbox["type"] == "checkbox" and checkbox["value"] == "true"
    assert "checked" in checkbox
    delete_form = next(
        form
        for form in parser.forms
        if any(item.get("name") == "token_id" for item in form)
    )
    assert not any(item.get("name", "").startswith("twofactor") for item in delete_form)
    unchecked = {
        item["name"]: item.get("value", "")
        for item in settings
        if item.get("type") == "hidden"
    }
    disabled = client.post(f"/users/details/{user.id}", data=unchecked)
    assert disabled.status_code == 200
    db.expire_all()
    assert db.get(app_modules.models.User, user.id).twofactor == ""
    assert disabled.context["twofactorurl"] == ""
    checked = {**unchecked, "twofactor": checkbox["value"]}
    enabled = client.post(f"/users/details/{user.id}", data=checked)
    assert enabled.status_code == 200
    db.expire_all()
    secret = db.get(app_modules.models.User, user.id).twofactor
    assert len(secret) == 32
    assert enabled.context["twofactorurl"].startswith("otpauth://totp/")
    repeat = client.post(f"/users/details/{user.id}", data=checked)
    assert repeat.context["twofactorurl"] == ""
    db.expire_all()
    assert db.get(app_modules.models.User, user.id).twofactor == secret
