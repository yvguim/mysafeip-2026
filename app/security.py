"""
Passwords functions and IP utilities
"""

import ipaddress
from urllib.parse import urlparse

import bcrypt
from fastapi import Request

from settings import settings

BCRYPT_MAX_BYTES = 72


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """return true if password match hashed argument"""
    if len(plain_password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        return False
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    """hash a plain text string"""
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError("Password must not exceed 72 UTF-8 bytes")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def get_client_ip(request: Request) -> str:
    """
    Extrait l'IP réelle du client.
    Si TRUSTED_PROXIES est activé, utilise X-Forwarded-For ou X-Real-IP.
    Sinon, utilise request.client.host.
    """
    if settings.TRUSTED_PROXIES:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()
            if _is_valid_ip(ip):
                return ip

        real_ip = request.headers.get("x-real-ip")
        if real_ip and _is_valid_ip(real_ip):
            return real_ip

    if request.client:
        return request.client.host
    return "127.0.0.1"


def is_valid_url(url: str) -> bool:
    """Vérifie que l'URL utilise un schéma http(s) et possède un netloc."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _is_valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False
