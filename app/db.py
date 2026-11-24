from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import einstellungen


class Betrag(TypeDecorator):
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else int((Decimal(value) * 100).to_integral_value())

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value).scaleb(-2).quantize(Decimal("0.01"))


class Basis(DeclarativeBase):
    pass


class Beleg(Basis):
    __tablename__ = "belege"

    id: Mapped[int] = mapped_column(primary_key=True)
    dateiname: Mapped[str] = mapped_column(String(255))
    dateityp: Mapped[str] = mapped_column(String(50))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    extraktor: Mapped[str] = mapped_column(String(40))
    lieferant: Mapped[str | None] = mapped_column(String(255))
    lieferant_uid: Mapped[str | None] = mapped_column(String(20), index=True)
    empfaenger: Mapped[str | None] = mapped_column(String(255))
    rechnungsnummer: Mapped[str | None] = mapped_column(String(80))
    rechnungsdatum: Mapped[date | None] = mapped_column(Date)
    faellig_am: Mapped[date | None] = mapped_column(Date)
    iban: Mapped[str | None] = mapped_column(String(40))
    waehrung: Mapped[str] = mapped_column(String(3), default="EUR")
    netto: Mapped[Decimal | None] = mapped_column(Betrag)
    ust: Mapped[Decimal | None] = mapped_column(Betrag)
    brutto: Mapped[Decimal | None] = mapped_column(Betrag)
    steuerzeilen: Mapped[list] = mapped_column(JSON, default=list)
    konto: Mapped[str | None] = mapped_column(String(20))
    kostenstelle: Mapped[str | None] = mapped_column(String(20))
    hinweise: Mapped[list] = mapped_column(JSON, default=list)
    bestaetigte_iban: Mapped[str | None] = mapped_column(String(40))
    bearbeitet_von: Mapped[str | None] = mapped_column(String(80))
    freigegeben_von: Mapped[str | None] = mapped_column(String(80))
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Protokoll(Basis):
    __tablename__ = "protokoll"

    id: Mapped[int] = mapped_column(primary_key=True)
    beleg_id: Mapped[int] = mapped_column(ForeignKey("belege.id"), index=True)
    benutzer: Mapped[str] = mapped_column(String(80))
    aktion: Mapped[str] = mapped_column(String(30))
    details: Mapped[dict] = mapped_column(JSON)
    zeitpunkt: Mapped[str] = mapped_column(String(40))
    vorgaenger: Mapped[str] = mapped_column(String(64))
    pruefsumme: Mapped[str] = mapped_column(String(64))


@lru_cache
def sitzungen() -> sessionmaker:
    url = make_url(einstellungen().datenbank_url)
    argumente = {}
    if url.get_backend_name() == "sqlite":
        argumente = {"check_same_thread": False}
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=argumente, pool_pre_ping=True)
    Basis.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def datenbank():
    with sitzungen()() as sitzung:
        yield sitzung
