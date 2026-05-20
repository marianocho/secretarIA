"""Carrega e valida configuração a partir de .env."""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Variável de ambiente obrigatória '{name}' não definida. "
            f"Confira o .env (use .env.example como base)."
        )
    return value


def _required_int(name: str) -> int:
    raw = _required(name)
    try:
        return int(raw)
    except ValueError as e:
        raise RuntimeError(f"'{name}' deve ser um inteiro, recebi: {raw!r}") from e


TELEGRAM_BOT_TOKEN: str = _required("TELEGRAM_BOT_TOKEN")
ALLOWED_TELEGRAM_USER_ID: int = _required_int("ALLOWED_TELEGRAM_USER_ID")

TIMEZONE_NAME: str = os.getenv("TIMEZONE", "America/Sao_Paulo")
TIMEZONE: ZoneInfo = ZoneInfo(TIMEZONE_NAME)

STATE_FILE_PATH: Path = PROJECT_ROOT / os.getenv("STATE_FILE_PATH", "state.json")

GOOGLE_OAUTH_CLIENT_PATH: Path = PROJECT_ROOT / "credentials" / "google_oauth.json"
GOOGLE_TOKEN_PATH: Path = PROJECT_ROOT / "credentials" / "token.json"

GOOGLE_CALENDAR_SCOPES: list[str] = ["https://www.googleapis.com/auth/calendar.events"]
