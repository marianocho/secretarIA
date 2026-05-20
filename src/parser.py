"""Parsing de mensagem texto para ParsedEvent.

Formato aceito:
    <título> <DD/MM[/AAAA]> [<HH:MM>[-<HH:MM> | +Xh[Ym] | +Xm]] [@<local>] [#<notas>]

Estratégia: extrair os marcadores em camadas (notas → local → data → hora),
o que dá mensagens de erro específicas e código mais legível que uma regex
monolítica.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time as dt_time, timedelta
from typing import Callable

from src.models import ParsedEvent, ParseError

_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\b")
_RANGE_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")
_DURATION_RE = re.compile(r"^\+(?:(\d+)h)?(?:(\d+)m)?\s*$")


def _next_weekday_resolver(target_wd: int) -> Callable[[date], date]:
    """Devolve função que, dado 'hoje', retorna a próxima ocorrência de target_wd.
    Se hoje for o próprio target_wd, pula pra semana que vem (não retorna hoje).
    weekday(): 0=segunda ... 6=domingo."""

    def resolve(today: date) -> date:
        delta = (target_wd - today.weekday()) % 7
        if delta == 0:
            delta = 7
        return today + timedelta(days=delta)

    return resolve


# Ordem importa: padrões mais longos antes (depois de amanhã antes de amanhã).
_RELATIVE_DATE_PATTERNS: list[tuple[re.Pattern[str], Callable[[date], date]]] = [
    (
        re.compile(r"\bdepois\s+de\s+amanh[ãa]\b", re.IGNORECASE),
        lambda today: today + timedelta(days=2),
    ),
    (re.compile(r"\bamanh[ãa]\b", re.IGNORECASE), lambda today: today + timedelta(days=1)),
    (re.compile(r"\bhoje\b", re.IGNORECASE), lambda today: today),
    (re.compile(r"\bsegunda(?:-feira)?\b", re.IGNORECASE), _next_weekday_resolver(0)),
    (re.compile(r"\bter[çc]a(?:-feira)?\b", re.IGNORECASE), _next_weekday_resolver(1)),
    (re.compile(r"\bquarta(?:-feira)?\b", re.IGNORECASE), _next_weekday_resolver(2)),
    (re.compile(r"\bquinta(?:-feira)?\b", re.IGNORECASE), _next_weekday_resolver(3)),
    (re.compile(r"\bsexta(?:-feira)?\b", re.IGNORECASE), _next_weekday_resolver(4)),
    (re.compile(r"\bs[áa]bado\b", re.IGNORECASE), _next_weekday_resolver(5)),
    (re.compile(r"\bdomingo\b", re.IGNORECASE), _next_weekday_resolver(6)),
]


def _preprocess_relative_dates(text: str, now: datetime) -> str:
    """Substitui 'amanhã', 'domingo', etc. por DD/MM/AAAA. Só atua se não houver
    uma data numérica explícita — DD/MM no texto vence palavras relativas."""
    if _DATE_RE.search(text):
        return text
    today = now.date()
    for pattern, resolver in _RELATIVE_DATE_PATTERNS:
        if pattern.search(text):
            resolved = resolver(today)
            return pattern.sub(resolved.strftime("%d/%m/%Y"), text, count=1)
    return text

EXAMPLES_TEXT = (
    "Exemplos:\n"
    "  Dentista 18/05 16:00\n"
    "  Dentista amanhã 16:00\n"
    "  Happy hour sexta 19:00\n"
    "  Aula 15/05 19:00-21:00\n"
    "  Reunião 18/05 14:00 +30m\n"
    "  Festa 01/06 20:00 @ casa do Greg\n"
    "  Aniversário 12/07\n"
    "  Prova 22/05 14:00 @ FCT # cadeira de SO"
)


def parse(text: str, now: datetime) -> ParsedEvent | ParseError:
    text = text.strip()
    if not text:
        return ParseError("mensagem vazia")

    text, notes = _extract_after("#", text)
    text, location = _extract_after("@", text)
    text = _preprocess_relative_dates(text, now)

    date_match = _DATE_RE.search(text)
    if not date_match:
        return ParseError("não achei a data", "use DD/MM ou DD/MM/AAAA")

    title = text[: date_match.start()].strip()
    if not title:
        return ParseError("título vazio", "começa com o que é o evento")

    event_date = _resolve_date(date_match, now)
    if isinstance(event_date, ParseError):
        return event_date

    remainder = text[date_match.end() :].strip()
    return _build_event(
        title=title,
        event_date=event_date,
        remainder=remainder,
        location=location,
        notes=notes,
        tz=now.tzinfo,
    )


def _extract_after(marker: str, text: str) -> tuple[str, str | None]:
    """Se `marker` está em `text`, devolve (antes, depois.strip()). Senão (text, None)."""
    if marker not in text:
        return text, None
    before, _, after = text.partition(marker)
    cleaned = after.strip()
    return before.strip(), cleaned or None


def _resolve_date(match: re.Match[str], now: datetime) -> date | ParseError:
    day_s, month_s, year_s = match.group(1), match.group(2), match.group(3)
    day = int(day_s)
    month = int(month_s)

    if year_s is None:
        year = now.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            return ParseError(
                "data inválida",
                f"{day_s}/{month_s} não existe",
            )
        if candidate < now.date():
            year += 1
            try:
                candidate = date(year, month, day)
            except ValueError:
                return ParseError("data inválida", f"{day_s}/{month_s} não existe no próximo ano")
        return candidate

    year = int(year_s)
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return ParseError("data inválida", f"{day_s}/{month_s}/{year_s} não existe")


def _build_event(
    *,
    title: str,
    event_date: date,
    remainder: str,
    location: str | None,
    notes: str | None,
    tz,
) -> ParsedEvent | ParseError:
    if not remainder:
        return _all_day(title, event_date, location, notes, tz)

    range_match = _RANGE_RE.match(remainder)
    if range_match:
        return _from_range(title, event_date, range_match, location, notes, tz)

    time_match = _TIME_RE.match(remainder)
    if not time_match:
        return ParseError("não entendi a hora", remainder)

    try:
        start_time = dt_time(int(time_match.group(1)), int(time_match.group(2)))
    except ValueError:
        return ParseError("hora inválida", time_match.group(0))

    rest = remainder[time_match.end() :].strip()
    start_dt = datetime.combine(event_date, start_time, tzinfo=tz)

    if not rest:
        return ParsedEvent(
            title=title,
            start=start_dt,
            end=start_dt + timedelta(hours=1),
            is_all_day=False,
            location=location,
            notes=notes,
        )

    dur_match = _DURATION_RE.match(rest)
    if not dur_match or not (dur_match.group(1) or dur_match.group(2)):
        return ParseError(
            "formato após hora não reconhecido",
            f"esperava +Xh, +Xm, +XhYm ou nada (depois de '{time_match.group(0)}'), recebi '{rest}'",
        )

    hours = int(dur_match.group(1) or 0)
    minutes = int(dur_match.group(2) or 0)
    return ParsedEvent(
        title=title,
        start=start_dt,
        end=start_dt + timedelta(hours=hours, minutes=minutes),
        is_all_day=False,
        location=location,
        notes=notes,
    )


def _from_range(
    title: str,
    event_date: date,
    match: re.Match[str],
    location: str | None,
    notes: str | None,
    tz,
) -> ParsedEvent | ParseError:
    try:
        start_t = dt_time(int(match.group(1)), int(match.group(2)))
        end_t = dt_time(int(match.group(3)), int(match.group(4)))
    except ValueError:
        return ParseError("hora inválida no intervalo", match.group(0))

    start_dt = datetime.combine(event_date, start_t, tzinfo=tz)
    end_dt = datetime.combine(event_date, end_t, tzinfo=tz)
    if end_dt <= start_dt:
        return ParseError(
            "hora final precisa ser depois da inicial",
            f"{match.group(1)}:{match.group(2)} → {match.group(3)}:{match.group(4)}",
        )
    return ParsedEvent(
        title=title,
        start=start_dt,
        end=end_dt,
        is_all_day=False,
        location=location,
        notes=notes,
    )


def _all_day(
    title: str,
    event_date: date,
    location: str | None,
    notes: str | None,
    tz,
) -> ParsedEvent:
    start_dt = datetime.combine(event_date, dt_time.min, tzinfo=tz)
    end_dt = start_dt + timedelta(days=1)
    return ParsedEvent(
        title=title,
        start=start_dt,
        end=end_dt,
        is_all_day=True,
        location=location,
        notes=notes,
    )
