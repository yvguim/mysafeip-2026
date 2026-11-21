"""
External settings configuration
"""

import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    External variables loaded from .env file
    """

    load_dotenv()

    DISABLE_REGISTER: bool = os.getenv("DISABLE_REGISTER")
    JWT_SECRET: str = os.getenv("JWT_SECRET")
    SETUP_TOKEN: str = os.getenv("SETUP_TOKEN", "")
    ALGORITHM: str = os.getenv("ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")
    SQLALCHEMY_DATABASE_URI: str = os.getenv("SQLALCHEMY_DATABASE_URI")
    URL_WEBSITE: str = os.getenv("URL_WEBSITE")
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE")
    ADMIN_SEE_USERS_IP: bool = os.getenv("ADMIN_SEE_USERS_IP")
    TRUSTED_PROXIES: bool = os.getenv("TRUSTED_PROXIES", "false").lower() == "true"


settings = Settings()
