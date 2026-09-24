from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.vps_config import get_vps_settings


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class VpsBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _connect_args(database_url: str) -> dict[str, bool]:
    return {"check_same_thread": False} if database_url.startswith("sqlite") else {}


def build_engine(database_url: str, *, sql_echo: bool) -> Engine:
    return create_engine(
        database_url,
        echo=sql_echo,
        future=True,
        connect_args=_connect_args(database_url),
    )


def build_session_factory(database_url: str, *, sql_echo: bool) -> sessionmaker[Session]:
    return sessionmaker(
        bind=build_engine(database_url, sql_echo=sql_echo),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_vps_settings()
    return build_engine(settings.database_url, sql_echo=settings.sql_echo)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
