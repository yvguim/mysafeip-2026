from datetime import datetime

from pydantic import BaseModel, EmailStr


class IpCreate(BaseModel):
    model_config = {"from_attributes": True}

    id: int | None = None
    owner_id: int | None = None
    value: str
    description: str | None = None
    origin: str = None
    expires_at: datetime | None = None
    is_permanent: bool = False


class Ip(BaseModel):
    model_config = {"from_attributes": True}

    id: int | None = None
    owner_id: int | None = None
    value: str
    description: str | None = None
    origin: str = None
    expires_at: datetime | None = None
    is_permanent: bool = False


class UserCreate(BaseModel):
    model_config = {"from_attributes": True}

    id: int | None = None
    is_active: bool | None = True
    ips: list = []
    email: EmailStr
    is_admin: bool | None = False
    twofactor: str = None
    ip_default_ttl_hours: int = 1
    ia_default_ttl_hours: int = 24
    password: str


class User(BaseModel):
    model_config = {"from_attributes": True}

    id: int | None = None
    is_active: bool | None = True
    ips: list = []
    email: EmailStr
    is_admin: bool | None = False
    twofactor: str = None
    ip_default_ttl_hours: int = 1
    ia_default_ttl_hours: int = 24


class TokenData(BaseModel):
    username: str | None = None


class Token(BaseModel):
    model_config = {"from_attributes": True}

    id: int | None = None
    owner_id: int | None = None
    key: str = None
    secret: str = None
    description: str | None = None


class TokenCreate(Token):
    pass


class InstantAccess(BaseModel):
    model_config = {"from_attributes": True}

    id: int | None = None
    owner_id: int | None = None
    link: str
    unique_link: str = None
    description: str | None = None
    expires_at: datetime | None = None
    is_permanent: bool = False


class InstantAccessCreate(InstantAccess):
    pass
