"""Testes do calendar_client. Não chama a API do Google de verdade —
foca em _build_event_body, que é puro (ParsedEvent → dict).

A função que escreve/lê do Google (create_event, find_conflicts,
update_event_times) seria caro de testar sem mocks pesados; verificadas
manualmente no fluxo end-to-end.

Como rodar:
    python tests/test_calendar_client.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_USER_ID", "0")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.calendar_client import _build_event_body  # noqa: E402
from src.models import ParsedEvent  # noqa: E402

TZ = ZoneInfo("America/Sao_Paulo")


def _timed(title="Reunião", location=None, notes=None) -> ParsedEvent:
    return ParsedEvent(
        title=title,
        start=datetime(2026, 5, 11, 14, 0, tzinfo=TZ),
        end=datetime(2026, 5, 11, 15, 0, tzinfo=TZ),
        is_all_day=False,
        location=location,
        notes=notes,
    )


def _all_day(title="Aniversário") -> ParsedEvent:
    return ParsedEvent(
        title=title,
        start=datetime(2026, 7, 12, 0, 0, tzinfo=TZ),
        end=datetime(2026, 7, 13, 0, 0, tzinfo=TZ),
        is_all_day=True,
        location=None,
        notes=None,
    )


# ---------------------- timed events ----------------------

def test_timed_body_has_summary():
    body = _build_event_body(_timed())
    assert body["summary"] == "Reunião"


def test_timed_body_uses_dateTime_not_date():
    body = _build_event_body(_timed())
    assert "dateTime" in body["start"]
    assert "date" not in body["start"]
    assert "dateTime" in body["end"]


def test_timed_body_includes_timezone():
    body = _build_event_body(_timed())
    assert body["start"]["timeZone"] == "America/Sao_Paulo"
    assert body["end"]["timeZone"] == "America/Sao_Paulo"


def test_timed_body_iso_format_with_offset():
    body = _build_event_body(_timed())
    # isoformat de datetime com tzinfo inclui offset (-03:00 pra SP)
    assert "-03:00" in body["start"]["dateTime"]


def test_timed_body_omits_location_when_none():
    body = _build_event_body(_timed())
    assert "location" not in body


def test_timed_body_omits_description_when_none():
    body = _build_event_body(_timed())
    assert "description" not in body


def test_timed_body_includes_location():
    body = _build_event_body(_timed(location="Sala A"))
    assert body["location"] == "Sala A"


def test_timed_body_includes_description():
    body = _build_event_body(_timed(notes="levar laptop"))
    assert body["description"] == "levar laptop"


def test_timed_body_both_location_and_notes():
    body = _build_event_body(_timed(location="Sala A", notes="trazer slides"))
    assert body["location"] == "Sala A"
    assert body["description"] == "trazer slides"


# ---------------------- all-day events ----------------------

def test_all_day_body_uses_date_not_dateTime():
    body = _build_event_body(_all_day())
    assert "date" in body["start"]
    assert "dateTime" not in body["start"]
    assert "date" in body["end"]
    assert "dateTime" not in body["end"]


def test_all_day_body_no_timezone():
    body = _build_event_body(_all_day())
    # all-day não tem timeZone (data é "naked", sem offset)
    assert "timeZone" not in body["start"]
    assert "timeZone" not in body["end"]


def test_all_day_body_end_is_exclusive():
    # Convenção Google: all-day event de 1 dia em 12/07 → start=12/07, end=13/07
    body = _build_event_body(_all_day())
    assert body["start"]["date"] == "2026-07-12"
    assert body["end"]["date"] == "2026-07-13"


def test_all_day_body_summary_correct():
    body = _build_event_body(_all_day(title="Aniversário do João"))
    assert body["summary"] == "Aniversário do João"


# ---------------------- runner standalone ----------------------

if __name__ == "__main__":
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failed: list[str] = []
    for name, fn in tests:
        try:
            fn()
            print(f"  [OK]   {name}")
        except AssertionError as e:
            print(f"  [FAIL] {name}: AssertionError {e}")
            failed.append(name)
        except Exception as e:
            print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
            failed.append(name)
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
