from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class InitialSetup(Base):
    """A singleton row marks a new installation that has not created an account."""

    __tablename__ = "initial_setup"

    id = Column(Integer, primary_key=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    ips = relationship("Ip", back_populates="owner", cascade="all, delete-orphan")
    instantaccess = relationship(
        "InstantAccess", back_populates="owner", cascade="all, delete-orphan"
    )
    token = relationship("Token", back_populates="owner", cascade="all, delete-orphan")
    twofactor = Column(String, default="")
    ip_default_ttl_hours = Column(Integer, default=1)
    ia_default_ttl_hours = Column(Integer, default=24)


class Ip(Base):
    __tablename__ = "ips"

    id = Column(Integer, primary_key=True, index=True)
    value = Column(String, index=True)
    description = Column(String, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    origin = Column(String, index=True)
    expires_at = Column(DateTime, nullable=True)
    is_permanent = Column(Boolean, default=False)
    owner = relationship("User", back_populates="ips")


class InstantAccess(Base):
    __tablename__ = "instantaccess"

    id = Column(Integer, primary_key=True, index=True)
    link = Column(String, index=True)
    unique_link = Column(String, index=True)
    description = Column(String, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    expires_at = Column(DateTime, nullable=True)
    is_permanent = Column(Boolean, default=False)
    owner = relationship("User", back_populates="instantaccess")


class Token(Base):
    __tablename__ = "token"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, index=True)
    secret = Column(String, index=True)
    description = Column(String, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="token")
