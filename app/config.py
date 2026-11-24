from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

Rolle = Literal["eingang", "buchhaltung", "freigabe"]


class Benutzer(BaseModel):
    name: str
    rollen: list[Rolle]


class Einstellungen(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BELEGFLOW_", extra="ignore")

    datenbank_url: str = "sqlite:///./daten/belegflow.db"
    speicher: Path = Path("./daten/belege")
    extraktor: Literal["regeln", "claude"] = "regeln"
    claude_modell: str = "claude-opus-5-5"
    max_mb: int = 10
    steuersaetze: list[str] = ["0", "10", "13", "20"]
    benutzer: dict[str, Benutzer] = {}


@lru_cache
def einstellungen() -> Einstellungen:
    return Einstellungen()
