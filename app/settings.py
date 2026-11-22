"""
External settings configuration
"""

import logging
import os
from secrets import token_hex

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    External variables loaded from .env file
    """

    load_dotenv()

    DISABLE_REGISTER: bool = os.getenv("DISABLE_REGISTER")
    JWT_SECRET: str = ""
    ALGORITHM: str = os.getenv("ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")
    SQLALCHEMY_DATABASE_URI: str = os.getenv("SQLALCHEMY_DATABASE_URI")
    URL_WEBSITE: str = os.getenv("URL_WEBSITE")
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE")
    ADMIN_SEE_USERS_IP: bool = os.getenv("ADMIN_SEE_USERS_IP")
    TRUSTED_PROXIES: bool = os.getenv("TRUSTED_PROXIES", "false").lower() == "true"

    @field_validator("JWT_SECRET")
    @classmethod
    def default_jwt_secret(cls, value: str) -> str:
        if value.strip():
            return value
        logging.getLogger(__name__).warning(
            "Configure JWT_SECRET to keep sessions across restarts; "
            "using a temporary signing secret for this startup."
        )
        return token_hex(32)


settings = Settings()
