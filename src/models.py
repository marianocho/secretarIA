"""Tipos de domínio compartilhados entre parser, bot e calendar_client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ParsedEvent:
    """Evento parseado de uma mensagem.

    Contrato com o calendar_client:
    - Para eventos com hora: `start` e `end` são datetimes com tzinfo.
    - Para all-day: `start` e `end` são datetimes (00:00) e `end` é
      EXCLUSIVO (convenção do Google Calendar). Evento de 1 dia no
      12/07 → start=12/07 00:00, end=13/07 00:00.
    """

    title: str
    start: datetime
    end: datetime
    is_all_day: bool
    location: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ParseError:
    message: str
    detail: str | None = None


@dataclass(frozen=True)
class ExistingEvent:
    """Evento já existente no calendário, lido via API. Usado pra detecção
    de conflito e como referência pra mover (patch)."""

    event_id: str
    summary: str
    start: datetime
    end: datetime
    html_link: str
