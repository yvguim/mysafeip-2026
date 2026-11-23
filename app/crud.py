import secrets
from datetime import datetime, timedelta

import pyotp
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

import security
from models import InitialSetup, InstantAccess, Ip, Token, User
from schemas import TokenCreate, UserCreate
from settings import settings


def get_user(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()


def get_users(db: Session):
    return db.query(User).all()


def create_user(db: Session, user: UserCreate):
    db_user = User(
        email=user.email,
        is_admin=user.is_admin,
        hashed_password=security.get_password_hash(user.password),
    )
    db.execute(delete(InitialSetup).where(InitialSetup.id == 1))
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def reset_user_password(db: Session, user: User, password: str) -> bool:
    # A concurrent change must not be overwritten using a stale password check.
    result = db.connection().execute(
        update(User.__table__)
        .where(User.id == user.id, User.hashed_password == user.hashed_password)
        .values(hashed_password=security.get_password_hash(password))
    )
    if result.rowcount != 1:
        return False
    db.commit()
    return True


def enable_user_twofactor(db: Session, user: User):
    user = db.query(User).get(user.id)
    user.twofactor = pyotp.random_base32(length=32)  # 160 bits before Base32 encoding.
    db.commit()
    db.refresh(user)
    return user


def disable_user_twofactor(db: Session, user: User):
    user = db.query(User).get(user.id)
    user.twofactor = ""
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, email):
    db_user = get_user_by_email(db, email)
    if not db_user:
        return False
    db.delete(db_user)
    db.commit()
    return True


def get_ips(db: Session, user):
    """List visible IPs, excluding non-permanent rows whose expiry has been reached."""
    query = db.query(Ip).filter(Ip.owner == user)
    if user.is_admin and settings.ADMIN_SEE_USERS_IP:
        query = db.query(Ip)
    # Enforce expiry on reads, without waiting for the cleanup scheduler.
    return query.filter(
        (Ip.is_permanent.is_(True))
        | (Ip.expires_at.is_(None))
        | (Ip.expires_at > datetime.now())
    ).all()


def get_ip(db: Session, ip_id: int):
    return db.query(Ip).get(ip_id)


def delete_ip(db: Session, id, *, owner_id: int) -> bool:
    """Delete only an IP owned by the explicitly supplied account."""
    db_ip = db.query(Ip).filter(Ip.id == id, Ip.owner_id == owner_id).first()
    if not db_ip:
        return False
    db.delete(db_ip)
    db.commit()
    return True


def delete_expired_ips(db: Session):
    expired_ips = (
        db.query(Ip)
        .filter(
            Ip.expires_at != None,
            Ip.expires_at < datetime.now(),
            Ip.is_permanent == False,
        )
        .all()
    )
    count = 0
    for ip in expired_ips:
        db.delete(ip)
        count += 1
    if count > 0:
        db.commit()
    return count


def delete_expired_links(db: Session):
    expired_links = (
        db.query(InstantAccess)
        .filter(
            InstantAccess.expires_at != None,
            InstantAccess.expires_at < datetime.now(),
            InstantAccess.is_permanent == False,
        )
        .all()
    )
    count = 0
    for link in expired_links:
        db.delete(link)
        count += 1
    if count > 0:
        db.commit()
    return count


def get_ip_for_user(db: Session, user_id: int, ip, origin, description):
    return (
        db.query(Ip)
        .filter(
            Ip.owner_id == user_id,
            Ip.value == ip.strip(),
            Ip.origin == origin,
            Ip.description == description,
        )
        .first()
    )


def create_user_ip(
    db: Session,
    user_id: int,
    ip,
    origin="",
    description="",
    ttl_hours=None,
    is_permanent=False,
):
    ip_exists = get_ip_for_user(
        db, user_id=user_id, ip=ip, origin=origin, description=description
    )
    if not ip_exists:
        ip_data = {
            "description": description,
            "value": ip,
            "origin": origin,
            "owner_id": user_id,
        }

        if is_permanent:
            ip_data["is_permanent"] = True
            ip_data["expires_at"] = None
        elif ttl_hours:
            ip_data["expires_at"] = datetime.now() + timedelta(hours=ttl_hours)

        db_ip = Ip(**ip_data)
        db.add(db_ip)
        db.commit()
        db.refresh(db_ip)
        return db_ip
    return ip_exists


def create_instant_access(
    db: Session,
    link: str,
    user_id: int,
    description="",
    ttl_hours=None,
    is_permanent=False,
):
    unique_link = secrets.token_hex(16)
    ia_data = {
        "link": link,
        "unique_link": unique_link,
        "owner_id": user_id,
        "description": description,
    }

    if is_permanent:
        ia_data["is_permanent"] = True
        ia_data["expires_at"] = None
    elif ttl_hours:
        ia_data["expires_at"] = datetime.now() + timedelta(hours=ttl_hours)

    db_ia = InstantAccess(**ia_data)
    db.add(db_ia)
    db.commit()
    db.refresh(db_ia)
    return db_ia


def create_new_token(db, user_id: int, description: None):
    key = secrets.token_hex(16)
    secret = secrets.token_hex(32)
    token = TokenCreate(
        key=key, secret=secret, owner_id=user_id, description=description
    )
    token_data = token.dict()
    db_token = Token(
        description=token_data["description"],
        key=str(token_data["key"]),
        secret=security.get_password_hash(token_data["secret"]),
        owner_id=token_data["owner_id"],
    )
    db.add(db_token)
    db.commit()
    db.refresh(db_token)
    return {"key": db_token.key, "secret": secret}


def get_tokens(db: Session, user):
    return db.query(Token).filter(Token.owner == user)


def get_token(db: Session, id):
    return db.query(Token).get(id)


def delete_token(db: Session, id, *, owner_id: int) -> bool:
    """Delete only an API token owned by the explicitly supplied account."""
    db_token = (
        db.query(Token).filter(Token.id == id, Token.owner_id == owner_id).first()
    )
    if not db_token:
        return False
    db.delete(db_token)
    db.commit()
    return True


def get_link(db: Session, link_id: int):
    return db.query(InstantAccess).get(link_id)


def get_links(db: Session, user):
    return db.query(InstantAccess).filter(InstantAccess.owner == user)


def get_link_by_unique_link(db: Session, unique_link: str):
    return (
        db.query(InstantAccess).filter(InstantAccess.unique_link == unique_link).first()
    )


def update_user_ttl(
    db: Session, user: User, ttl_hours: int, ia_ttl_hours: int | None = None
):
    user.ip_default_ttl_hours = ttl_hours
    if ia_ttl_hours is not None:
        user.ia_default_ttl_hours = ia_ttl_hours
    db.commit()
    db.refresh(user)
    return user


def delete_link(db: Session, id, *, owner_id: int) -> bool:
    """Delete an owned link and its associated IPs in a single transaction."""
    db_link = (
        db.query(InstantAccess)
        .filter(InstantAccess.id == id, InstantAccess.owner_id == owner_id)
        .first()
    )
    if not db_link:
        return False
    origin = db_link.unique_link
    ips_to_delete = (
        db.query(Ip).filter(Ip.origin == origin, Ip.owner_id == owner_id).all()
    )
    for ip in ips_to_delete:
        db.delete(ip)
    db.delete(db_link)
    db.commit()
    return True
