from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Einstellungen(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BELEGFLOW_", extra="ignore")

    datenbank_url: str = "sqlite:///./daten/belegflow.db"
    speicher: Path = Path("./daten/belege")
    extraktor: Literal["regeln", "modell"] = "regeln"
    modell: str = ""
    max_mb: int = 10
    steuersaetze: list[str] = ["0", "10", "13", "20"]
    sichere_cookies: bool = True
    sitzung_stunden: int = 12
    wechselkurse: bool = True


@lru_cache
def einstellungen() -> Einstellungen:
    return Einstellungen()
