"""
Database configuration and utilities
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from settings import settings

SQLALCHEMY_DATABASE_URL = settings.SQLALCHEMY_DATABASE_URI

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def initialize_database(bind: Engine):
    from models import InitialSetup

    if bind.dialect.name != "sqlite":
        Base.metadata.create_all(bind)
        return

    name = bind.url.database
    file_backed = name not in (None, "", ":memory:", "file:", "file::memory:") and (
        bind.url.query.get("mode") != "memory"
    )
    with bind.begin() as connection:
        # Serialize schema creation and eligibility in one SQLite transaction.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        # Connecting can create the file before a second process acquires the lock.
        # Check the schema, not the path, inside the transaction.
        needs_setup = (
            file_backed
            and connection.exec_driver_sql("PRAGMA schema_version").scalar_one() == 0
            and connection.exec_driver_sql(
                "SELECT 1 FROM sqlite_schema LIMIT 1"
            ).first()
            is None
        )
        Base.metadata.create_all(connection)
        if needs_setup:
            connection.execute(InitialSetup.__table__.insert().values(id=1))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
