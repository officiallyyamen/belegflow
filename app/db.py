from datetime import UTC
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from sqlalchemy import DateTime, Integer, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import einstellungen


class Betrag(TypeDecorator):
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else int((Decimal(value) * 100).to_integral_value())

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value).scaleb(-2).quantize(Decimal("0.01"))


class Zeit(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Basis(DeclarativeBase):
    pass


def engine_fuer(adresse: str):
    url = make_url(adresse)
    if url.get_backend_name() != "sqlite":
        return create_engine(url, pool_pre_ping=True)
    if url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def verbinden(verbindung, _):
        verbindung.execute("PRAGMA foreign_keys=ON")
        verbindung.execute("PRAGMA journal_mode=WAL")

    return engine


@lru_cache
def sitzungen() -> sessionmaker:
    from . import modelle

    engine = engine_fuer(einstellungen().datenbank_url)
    if engine.dialect.name == "sqlite":
        modelle.Basis.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def datenbank():
    with sitzungen()() as sitzung:
        yield sitzung
