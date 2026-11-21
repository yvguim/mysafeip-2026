"""Characterize CRUD, cleanup clocks, schemas and pure validation helpers."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.characterization


@pytest.mark.parametrize("model_name", ["Ip", "InstantAccess"])
def test_cleanup_keeps_active_and_permanent_rows(
    db, user, app_modules, frozen_time, model_name
):
    model = getattr(app_modules.models, model_name)
    rows = []
    for offset, permanent in [
        (-1, False),
        (1, False),
        (-1, True),
        (None, False),
        (0, False),
    ]:
        attributes = {
            "owner_id": user.id,
            "is_permanent": permanent,
            "expires_at": frozen_time + timedelta(seconds=offset)
            if offset is not None
            else None,
        }
        if model_name == "Ip":
            attributes.update(value=f"192.0.2.{len(rows) + 1}", origin="synthetic")
        else:
            attributes.update(
                link="https://example.com", unique_link=f"link{len(rows)}"
            )
        row = model(**attributes)
        db.add(row)
        rows.append(row)
    db.commit()
    ids = [row.id for row in rows]
    cleanup = (
        app_modules.crud.delete_expired_ips
        if model_name == "Ip"
        else app_modules.crud.delete_expired_links
    )
    assert cleanup(db) == 1
    db.expire_all()
    assert db.get(model, ids[0]) is None
    assert {row.id for row in db.query(model).all()} == set(ids[1:])
    assert cleanup(db) == 0


def test_expired_link_cleanup_currently_keeps_origin_ips(
    db, user, app_modules, frozen_time
):
    """Deliberately characterize current asymmetry, pending product decision #9."""
    link = app_modules.crud.create_instant_access(
        db, "https://example.com", user.id, ttl_hours=1
    )
    link_id = link.id
    entry = app_modules.crud.create_user_ip(
        db, user.id, "192.0.2.20", origin=link.unique_link, ttl_hours=24
    )
    entry_id = entry.id
    link.expires_at = frozen_time - timedelta(seconds=1)
    db.commit()
    removed = app_modules.crud.delete_expired_links(db)
    assert removed == 1
    db.expire_all()
    assert db.get(app_modules.models.InstantAccess, link_id) is None
    assert db.get(app_modules.models.Ip, entry_id) is not None


def test_scheduler_callbacks_use_the_temporary_session(
    db, user, app_modules, frozen_time
):
    entry = app_modules.crud.create_user_ip(db, user.id, "192.0.2.20", ttl_hours=-1)
    link = app_modules.crud.create_instant_access(
        db, "https://example.com", user.id, ttl_hours=-1
    )
    entry_id, link_id = entry.id, link.id
    app_modules.main.cleanup_expired_ips()
    app_modules.main.cleanup_expired_links()
    db.expire_all()
    assert db.get(app_modules.models.Ip, entry_id) is None
    assert db.get(app_modules.models.InstantAccess, link_id) is None


def test_ip_deduplication_currently_does_not_renew_ttl(
    db, user, app_modules, frozen_time
):
    """Current composite duplicate behavior; do not prescribe renewal until #9."""
    first = app_modules.crud.create_user_ip(
        db, user.id, "192.0.2.20", "manual", "same", ttl_hours=1
    )
    second = app_modules.crud.create_user_ip(
        db, user.id, "192.0.2.20", "manual", "same", ttl_hours=9
    )
    assert first.id == second.id
    assert second.expires_at == frozen_time + timedelta(hours=1)
    assert db.query(app_modules.models.Ip).count() == 1


@pytest.mark.parametrize("changed", ["owner", "description", "origin"])
def test_same_address_is_distinct_when_composite_identity_changes(
    db, user, other_user, app_modules, changed
):
    first = app_modules.crud.create_user_ip(db, user.id, "192.0.2.20", "manual", "same")
    second = app_modules.crud.create_user_ip(
        db,
        other_user.id if changed == "owner" else user.id,
        "192.0.2.20",
        "other" if changed == "origin" else "manual",
        "other" if changed == "description" else "same",
    )
    assert second.id != first.id
    assert db.query(app_modules.models.Ip).count() == 2


def test_user_creation_hashes_password_and_exposes_no_hash_in_user_schema(
    db, app_modules, password
):
    payload = app_modules.schemas.UserCreate(
        email="synthetic@example.com", password=password
    )
    user = app_modules.crud.create_user(db, payload)
    assert user.hashed_password != password
    assert app_modules.security.verify_password(password, user.hashed_password)
    assert not app_modules.security.verify_password(
        "Wrong-only-42!", user.hashed_password
    )
    assert user.is_active is True
    assert user.is_admin is False
    assert user.ip_default_ttl_hours == 1
    assert user.ia_default_ttl_hours == 24
    public = app_modules.schemas.User.model_validate(user).model_dump()
    assert "hashed_password" not in public
    assert "password" not in public


def test_delete_user_cascades_resources_but_not_other_owner(
    db, user, other_user, app_modules
):
    ip = app_modules.crud.create_user_ip(db, user.id, "192.0.2.20")
    link = app_modules.crud.create_instant_access(db, "https://example.com", user.id)
    app_modules.crud.create_new_token(db, user.id, "synthetic")
    other = app_modules.crud.create_user_ip(db, other_user.id, "192.0.2.21")
    ids = (user.id, ip.id, link.id, other.id)
    deleted = app_modules.crud.delete_user(db, user.email)
    assert deleted is True
    db.expire_all()
    assert db.get(app_modules.models.User, ids[0]) is None
    assert db.get(app_modules.models.Ip, ids[1]) is None
    assert db.get(app_modules.models.InstantAccess, ids[2]) is None
    assert db.query(app_modules.models.Token).count() == 0
    assert db.get(app_modules.models.Ip, ids[3]) is not None
    assert app_modules.crud.delete_user(db, "missing@example.com") is False


@pytest.mark.parametrize("operation", ["delete_ip", "delete_link", "delete_token"])
def test_deleting_unknown_resource_returns_false(db, user, app_modules, operation):
    removed = getattr(app_modules.crud, operation)(db, 12345, owner_id=user.id)
    assert removed is False


@pytest.mark.parametrize(
    "email", ["not-email", "@example.com", "alice@", "alice example.com"]
)
def test_user_schema_rejects_invalid_email(app_modules, email):
    with pytest.raises(ValidationError):
        app_modules.schemas.UserCreate(email=email, password="synthetic")


def test_schema_defaults_and_independent_lists(app_modules):
    first = app_modules.schemas.UserCreate(
        email="first@example.com", password="synthetic"
    )
    second = app_modules.schemas.UserCreate(
        email="second@example.com", password="synthetic"
    )
    first.ips.append("synthetic")
    assert second.ips == []
    assert second.ip_default_ttl_hours == 1
    assert second.ia_default_ttl_hours == 24
    assert second.is_admin is False
    ip = app_modules.schemas.IpCreate(value="192.0.2.20")
    assert ip.is_permanent is False
    assert ip.expires_at is None


@pytest.mark.parametrize(
    "value,valid",
    [
        ("http://example.com", True),
        ("https://example.com/share", True),
        ("javascript:alert(1)", False),
        ("ftp://example.com", False),
        ("https:///host", False),
    ],
)
def test_url_validator(app_modules, value, valid):
    assert app_modules.security.is_valid_url(value) is valid


@pytest.mark.parametrize(
    "value,valid",
    [
        ("abc", False),
        ("abcdef", False),
        ("ABC123!", False),
        ("Abcdef!", False),
        ("Abc123", False),
        ("abc123!", False),
        ("Abc12!", True),
    ],
)
def test_current_signup_password_policy(app_modules, value, valid):
    assert app_modules.auth.password_validity(value) is valid
