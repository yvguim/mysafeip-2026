"""Characterize IP and instant-link HTTP behavior without selecting new TTL policy."""

from datetime import timedelta

import pytest

pytestmark = pytest.mark.characterization


@pytest.mark.parametrize("address", ["192.0.2.20", "2001:db8::20"])
def test_create_ip_and_export_exact_contract(
    client, login, user, db, app_modules, frozen_time, address
):
    login(client, user)
    response = client.post(
        "/ips/config/",
        data={"action": "create", "ip": address, "description": "synthetic"},
    )
    assert response.status_code == 200
    db.expire_all()
    entry = db.query(app_modules.models.Ip).one()
    assert entry.owner_id == user.id
    assert entry.value == address
    assert entry.description == "synthetic"
    assert entry.expires_at == frozen_time + timedelta(hours=1)
    assert entry.is_permanent is False
    response = client.get("/ips/config/", headers={"Cli": "true"})
    assert response.status_code == 200
    assert response.json() == [
        {"owner": user.email, "value": address, "description": "synthetic"}
    ]


def test_create_ip_uses_detected_peer_when_empty(client, login, user, db, app_modules):
    login(client, user)
    response = client.post("/ips/config/", data={"action": "create"})
    assert response.status_code == 200
    assert db.query(app_modules.models.Ip).one().value == "192.0.2.10"


@pytest.mark.parametrize(
    "address", ["not-an-ip", "192.0.2.999", "2001:::1", "192.0.2.1/24"]
)
def test_invalid_ip_does_not_create_row(client, login, user, db, app_modules, address):
    login(client, user)
    response = client.post("/ips/config/", data={"action": "create", "ip": address})
    assert response.status_code == 200
    assert (
        response.context["language"]["warning"]
        == response.context["language"]["Invalid-IP-address"]
    )
    assert db.query(app_modules.models.Ip).count() == 0


@pytest.mark.parametrize(
    "path,payload,model_name",
    [
        ("/ips/config/", {"ip": "192.0.2.20"}, "Ip"),
        (
            "/instant-access/config/",
            {"link": "https://example.com/share"},
            "InstantAccess",
        ),
    ],
)
@pytest.mark.parametrize(
    "mode,extra,hours,permanent",
    [
        ("standard", {"ttl_hours": "6"}, 6, False),
        ("custom", {"ttl_hours": "custom", "custom_ttl_hours": "9"}, 9, False),
        ("permanent", {"ttl_hours": "3", "is_permanent": "true"}, None, True),
    ],
)
def test_resource_ttl_and_permanence(
    client,
    login,
    user,
    db,
    app_modules,
    frozen_time,
    path,
    payload,
    model_name,
    mode,
    extra,
    hours,
    permanent,
):
    login(client, user)
    response = client.post(path, data={"action": "create", **payload, **extra})
    assert response.status_code == 200
    entry = db.query(getattr(app_modules.models, model_name)).one()
    assert entry.owner_id == user.id
    assert entry.is_permanent is permanent
    assert entry.expires_at == (
        None if permanent else frozen_time + timedelta(hours=hours)
    )


@pytest.mark.parametrize(
    "path,payload,model_name",
    [
        ("/ips/config/", {"ip": "192.0.2.20"}, "Ip"),
        (
            "/instant-access/config/",
            {"link": "https://example.com/share"},
            "InstantAccess",
        ),
    ],
)
@pytest.mark.parametrize("duration", ["0", "-1", "abc"])
def test_invalid_custom_duration_is_refused(
    client, login, user, db, app_modules, path, payload, model_name, duration
):
    login(client, user)
    response = client.post(
        path,
        data={
            "action": "create",
            **payload,
            "ttl_hours": "custom",
            "custom_ttl_hours": duration,
        },
    )
    assert response.status_code == 200
    assert (
        response.context["language"]["warning"]
        == response.context["language"]["Invalid-duration"]
    )
    assert db.query(getattr(app_modules.models, model_name)).count() == 0


def test_delete_own_ip_and_unknown_id(client, login, user, db, app_modules):
    login(client, user)
    entry = app_modules.crud.create_user_ip(db, user.id, "192.0.2.20", ttl_hours=1)
    entry_id = entry.id
    response = client.post("/ips/config/", data={"action": "delete", "ip_id": entry_id})
    assert response.status_code == 200
    db.expire_all()
    assert db.get(app_modules.models.Ip, entry_id) is None
    response = client.post("/ips/config/", data={"action": "delete", "ip_id": entry_id})
    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    assert db.query(app_modules.models.Ip).count() == 0


@pytest.mark.parametrize(
    "viewer,visibility,expected",
    [
        ("owner", False, {"192.0.2.20"}),
        ("owner", True, {"192.0.2.20"}),
        ("admin", False, {"192.0.2.30"}),
        ("admin", True, {"192.0.2.20", "192.0.2.21", "192.0.2.30"}),
    ],
)
def test_list_visibility(
    client,
    login,
    user,
    other_user,
    admin,
    db,
    app_modules,
    monkeypatch,
    viewer,
    visibility,
    expected,
):
    app_modules.crud.create_user_ip(db, user.id, "192.0.2.20")
    app_modules.crud.create_user_ip(db, other_user.id, "192.0.2.21")
    app_modules.crud.create_user_ip(db, admin.id, "192.0.2.30")
    monkeypatch.setattr(app_modules.settings.settings, "ADMIN_SEE_USERS_IP", visibility)
    login(client, admin if viewer == "admin" else user)
    response = client.get("/ips/config/", headers={"Cli": "1"})
    assert response.status_code == 200
    assert {entry["value"] for entry in response.json()} == expected
    page = client.get("/ips/config/")
    assert page.status_code == 200
    assert {entry.value for entry in page.context["ips"]} == expected


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_create_link_has_unique_identifier_and_default_ttl(
    client, login, user, db, app_modules, frozen_time, scheme
):
    login(client, user)
    response = client.post(
        "/instant-access/config/",
        data={
            "action": "create",
            "link": f"{scheme}://example.com/share",
            "description": "synthetic link",
        },
    )
    assert response.status_code == 200
    entry = db.query(app_modules.models.InstantAccess).one()
    assert entry.owner_id == user.id
    assert entry.link == f"{scheme}://example.com/share"
    assert entry.description == "synthetic link"
    assert len(entry.unique_link) == 32
    assert int(entry.unique_link, 16) >= 0
    assert entry.expires_at == frozen_time + timedelta(hours=24)


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "ftp://example.com", "https:///missing-host", "/local"],
)
def test_invalid_link_destination_is_refused(client, login, user, db, app_modules, url):
    login(client, user)
    response = client.post(
        "/instant-access/config/", data={"action": "create", "link": url}
    )
    assert response.status_code == 200
    assert (
        response.context["language"]["warning"]
        == response.context["language"]["Invalid-URL"]
    )
    assert db.query(app_modules.models.InstantAccess).count() == 0


def test_public_link_adds_visitor_to_owner_with_current_fixed_24h_ttl(
    client, user, db, app_modules, frozen_time
):
    """Current fixed TTL is characterization only; product decision tracked in #9."""
    link = app_modules.crud.create_instant_access(
        db, "https://example.com/share", user.id, ttl_hours=2
    )
    response = client.get(f"/instant-access/ia/{link.unique_link}")
    assert response.status_code == 200
    assert response.template.name == "redirect.html"
    assert response.context["link"] == link.link
    entry = db.query(app_modules.models.Ip).one()
    assert entry.owner_id == user.id
    assert entry.value == "192.0.2.10"
    assert entry.origin == link.unique_link
    assert entry.expires_at == frozen_time + timedelta(hours=24)


@pytest.mark.parametrize("kind", ["missing", "expired", "invalid_destination"])
def test_unusable_public_link_never_adds_ip(
    client, user, db, app_modules, frozen_time, kind
):
    identifier = "not-a-link"
    if kind != "missing":
        destination = (
            "javascript:alert(1)"
            if kind == "invalid_destination"
            else "https://example.com"
        )
        link = app_modules.crud.create_instant_access(
            db, destination, user.id, ttl_hours=1
        )
        if kind == "expired":
            link.expires_at = frozen_time - timedelta(seconds=1)
            db.commit()
        identifier = link.unique_link
    response = client.get(f"/instant-access/ia/{identifier}")
    assert response.status_code == 200
    assert response.template.name == "home.html"
    assert response.context["language"]["warning"]
    assert db.query(app_modules.models.Ip).count() == 0


def test_permanent_link_remains_usable_with_past_timestamp(
    client, user, db, app_modules, frozen_time
):
    link = app_modules.crud.create_instant_access(
        db, "https://example.com", user.id, is_permanent=True
    )
    link.expires_at = frozen_time - timedelta(days=1)
    db.commit()
    response = client.get(f"/instant-access/ia/{link.unique_link}")
    assert response.status_code == 200
    assert response.template.name == "redirect.html"
    assert db.query(app_modules.models.Ip).one().owner_id == user.id


def test_own_link_deletion_removes_only_associated_ips(
    client, login, user, other_user, db, app_modules
):
    login(client, user)
    link = app_modules.crud.create_instant_access(db, "https://example.com", user.id)
    link_id, origin = link.id, link.unique_link
    linked = app_modules.crud.create_user_ip(db, user.id, "192.0.2.20", origin=origin)
    unrelated = app_modules.crud.create_user_ip(
        db, other_user.id, "192.0.2.21", origin="unrelated"
    )
    linked_id, unrelated_id = linked.id, unrelated.id
    response = client.post(
        "/instant-access/config/", data={"action": "delete", "link_id": link_id}
    )
    assert response.status_code == 200
    db.expire_all()
    assert db.get(app_modules.models.InstantAccess, link_id) is None
    assert db.get(app_modules.models.Ip, linked_id) is None
    assert db.get(app_modules.models.Ip, unrelated_id) is not None


def test_link_listing_is_owner_scoped_even_for_admin(
    client, login, user, admin, db, app_modules
):
    own = app_modules.crud.create_instant_access(
        db, "https://example.com/admin", admin.id
    )
    app_modules.crud.create_instant_access(db, "https://example.com/private", user.id)
    login(client, admin)
    response = client.get("/instant-access/config/")
    assert response.status_code == 200
    assert [entry.id for entry in response.context["links"]] == [own.id]
    assert "https://example.com/private" not in response.text


def test_repeated_public_visit_currently_keeps_original_expiration(
    client, user, db, app_modules, frozen_time, monkeypatch
):
    """No renewal currently occurs; #9 must decide whether that should change."""
    link = app_modules.crud.create_instant_access(
        db, "https://example.com", user.id, ttl_hours=2
    )
    first = client.get(f"/instant-access/ia/{link.unique_link}")
    assert first.status_code == 200
    entry = db.query(app_modules.models.Ip).one()
    original = entry.expires_at
    entry.expires_at = frozen_time + timedelta(hours=1)
    db.commit()
    second = client.get(f"/instant-access/ia/{link.unique_link}")
    assert second.status_code == 200
    db.expire_all()
    assert db.query(app_modules.models.Ip).count() == 1
    assert db.query(app_modules.models.Ip).one().expires_at == frozen_time + timedelta(
        hours=1
    )
    assert original == frozen_time + timedelta(hours=24)
