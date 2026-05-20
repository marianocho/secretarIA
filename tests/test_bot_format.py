"""Testes dos formatadores puros do bot.py (sem I/O, sem Telegram).

bot.py importa config.py que valida env vars na importação. Pra tornar
o teste portável (rodar mesmo sem .env), setamos dummies ANTES do import.
python-dotenv não sobrescreve env vars já setadas, então valores reais
do .env do usuário também são respeitados.

Como rodar:
    python tests/test_bot_format.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy-token-for-tests")
os.environ.setdefault("ALLOWED_TELEGRAM_USER_ID", "0")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bot import (  # noqa: E402
    _Outcome,
    _build_conflict_prompt,
    _fmt_outcome_when,
    _format_backlog_summary,
    _format_conflict_block,
    _format_existing_when,
    _format_success,
    _format_when,
    _truncate,
)
from src.calendar_client import CreatedEvent  # noqa: E402
from src.models import ExistingEvent, ParsedEvent  # noqa: E402

TZ = ZoneInfo("America/Sao_Paulo")


def _event(
    title: str = "Reunião",
    start: datetime | None = None,
    end: datetime | None = None,
    all_day: bool = False,
    location: str | None = None,
    notes: str | None = None,
) -> ParsedEvent:
    return ParsedEvent(
        title=title,
        start=start or datetime(2026, 5, 11, 14, 0, tzinfo=TZ),
        end=end or datetime(2026, 5, 11, 15, 0, tzinfo=TZ),
        is_all_day=all_day,
        location=location,
        notes=notes,
    )


def _existing(
    summary: str = "Almoço",
    event_id: str = "abc",
    start: datetime | None = None,
    end: datetime | None = None,
) -> ExistingEvent:
    return ExistingEvent(
        event_id=event_id,
        summary=summary,
        start=start or datetime(2026, 5, 11, 12, 30, tzinfo=TZ),
        end=end or datetime(2026, 5, 11, 14, 30, tzinfo=TZ),
        html_link=f"https://calendar.google.com/{event_id}",
    )


def _created(link: str = "https://example.com/x") -> CreatedEvent:
    return CreatedEvent(event_id="x", html_link=link)


# ---------------------- _format_when ----------------------

def test_format_when_same_day():
    assert _format_when(_event()) == "11/05/2026 14:00–15:00"


def test_format_when_multi_day():
    e = _event(
        start=datetime(2026, 5, 11, 22, 0, tzinfo=TZ),
        end=datetime(2026, 5, 12, 1, 0, tzinfo=TZ),
    )
    assert _format_when(e) == "11/05 22:00 → 12/05 01:00"


def test_format_when_all_day():
    e = _event(
        start=datetime(2026, 7, 12, 0, 0, tzinfo=TZ),
        end=datetime(2026, 7, 13, 0, 0, tzinfo=TZ),
        all_day=True,
    )
    assert _format_when(e) == "12/07/2026 (dia inteiro)"


# ---------------------- _format_existing_when ----------------------

def test_format_existing_when_same_day():
    assert _format_existing_when(_existing()) == "12:30–14:30"


def test_format_existing_when_multi_day():
    e = _existing(
        start=datetime(2026, 5, 11, 22, 0, tzinfo=TZ),
        end=datetime(2026, 5, 12, 1, 0, tzinfo=TZ),
    )
    assert _format_existing_when(e) == "11/05 22:00 → 12/05 01:00"


# ---------------------- _format_conflict_block ----------------------

def test_conflict_block_single():
    result = _format_conflict_block([_existing()])
    assert "Conflito com" in result
    assert "Almoço" in result
    assert "12:30–14:30" in result


def test_conflict_block_multiple():
    conflicts = [
        _existing(summary="Almoço", event_id="a"),
        _existing(
            summary="Call",
            event_id="b",
            start=datetime(2026, 5, 11, 14, 0, tzinfo=TZ),
            end=datetime(2026, 5, 11, 14, 30, tzinfo=TZ),
        ),
    ]
    result = _format_conflict_block(conflicts)
    assert "2 eventos" in result
    assert "Almoço" in result
    assert "Call" in result


def test_conflict_block_more_than_5_truncates():
    conflicts = [_existing(summary=f"E{i}", event_id=str(i)) for i in range(7)]
    result = _format_conflict_block(conflicts)
    assert "7 eventos" in result
    assert "e mais 2" in result
    assert "E0" in result and "E4" in result
    assert "E5" not in result and "E6" not in result


# ---------------------- _format_success ----------------------

def test_format_success_basic():
    result = _format_success(_event(), _created(), [])
    assert "Reunião" in result
    assert "14:00–15:00" in result
    assert "https://example.com/x" in result
    assert "Conflito" not in result


def test_format_success_with_location_and_notes():
    e = _event(location="Sala A", notes="levar laptop")
    result = _format_success(e, _created(), [])
    assert "Sala A" in result
    assert "levar laptop" in result


def test_format_success_with_conflicts_includes_warning():
    result = _format_success(_event(), _created(), [_existing()])
    assert "Conflito" in result
    assert "Almoço" in result


def test_format_success_escapes_html_in_title():
    e = _event(title="A & B <script>")
    result = _format_success(e, _created(), [])
    assert "&amp;" in result
    assert "&lt;script&gt;" in result
    assert "<script>" not in result  # HTML cru não passa


# ---------------------- _build_conflict_prompt ----------------------

def test_conflict_prompt_text_includes_event_and_conflicts():
    body, _ = _build_conflict_prompt(_event(), [_existing()])
    assert "Reunião" in body
    assert "Almoço" in body
    assert "O que fazer?" in body


def test_conflict_prompt_has_create_button():
    _, markup = _build_conflict_prompt(_event(), [_existing()])
    flat = [btn for row in markup.inline_keyboard for btn in row]
    create_buttons = [b for b in flat if b.callback_data == "create"]
    assert len(create_buttons) == 1


def test_conflict_prompt_has_redo_button():
    _, markup = _build_conflict_prompt(_event(), [_existing()])
    flat = [btn for row in markup.inline_keyboard for btn in row]
    redo = [b for b in flat if b.callback_data == "redo"]
    assert len(redo) == 1


def test_conflict_prompt_one_move_per_conflict():
    conflicts = [
        _existing(summary="A", event_id="a"),
        _existing(summary="B", event_id="b"),
        _existing(summary="C", event_id="c"),
    ]
    _, markup = _build_conflict_prompt(_event(), conflicts)
    flat = [btn for row in markup.inline_keyboard for btn in row]
    move_buttons = [b for b in flat if (b.callback_data or "").startswith("move:")]
    assert len(move_buttons) == 3
    assert {b.callback_data for b in move_buttons} == {"move:0", "move:1", "move:2"}


def test_conflict_prompt_long_summary_truncates_in_button_label():
    long_name = "Reunião super longa com cliente super importante"
    conflicts = [_existing(summary=long_name, event_id="a")]
    _, markup = _build_conflict_prompt(_event(), conflicts)
    flat = [btn for row in markup.inline_keyboard for btn in row]
    move_btn = next(b for b in flat if b.callback_data == "move:0")
    assert "…" in move_btn.text
    assert len(move_btn.text) < 60


# ---------------------- _format_backlog_summary ----------------------

def test_backlog_summary_singular():
    outcomes = [
        _Outcome(
            text="a", success=True, title="X",
            start=datetime(2026, 5, 11, 14, 0, tzinfo=TZ),
            link="https://l/x",
        )
    ]
    result = _format_backlog_summary(outcomes)
    assert "1 mensagem)" in result
    assert "Criados (1)" in result
    assert "X" in result


def test_backlog_summary_plural():
    outcomes = [
        _Outcome(text="a", success=True, title="A",
                 start=datetime(2026, 5, 11, 14, 0, tzinfo=TZ), link="https://l/a"),
        _Outcome(text="b", success=True, title="B",
                 start=datetime(2026, 5, 11, 15, 0, tzinfo=TZ), link="https://l/b"),
    ]
    result = _format_backlog_summary(outcomes)
    assert "2 mensagens" in result


def test_backlog_summary_with_conflict_warning():
    outcomes = [
        _Outcome(
            text="a", success=True, title="A",
            start=datetime(2026, 5, 11, 14, 0, tzinfo=TZ),
            link="https://l/a",
            conflicts=[_existing()],
        )
    ]
    result = _format_backlog_summary(outcomes)
    assert "⚠️" in result


def test_backlog_summary_without_conflict_has_no_warning():
    outcomes = [
        _Outcome(
            text="a", success=True, title="A",
            start=datetime(2026, 5, 11, 14, 0, tzinfo=TZ),
            link="https://l/a",
        )
    ]
    result = _format_backlog_summary(outcomes)
    assert "⚠️" not in result


def test_backlog_summary_with_errors():
    outcomes = [
        _Outcome(text="lixo 99/99", success=False, error_msg="data inválida"),
    ]
    result = _format_backlog_summary(outcomes)
    assert "Erros (1)" in result
    assert "data inválida" in result


def test_backlog_summary_mixed():
    outcomes = [
        _Outcome(text="a", success=True, title="A",
                 start=datetime(2026, 5, 11, 14, 0, tzinfo=TZ), link="https://l/a"),
        _Outcome(text="lixo", success=False, error_msg="sem data"),
    ]
    result = _format_backlog_summary(outcomes)
    assert "Criados (1)" in result
    assert "Erros (1)" in result


# ---------------------- _fmt_outcome_when ----------------------

def test_fmt_outcome_when_timed():
    o = _Outcome(
        text="", success=True, title="X",
        start=datetime(2026, 5, 11, 14, 0, tzinfo=TZ),
        is_all_day=False,
    )
    assert _fmt_outcome_when(o) == "11/05 14:00"


def test_fmt_outcome_when_all_day():
    o = _Outcome(
        text="", success=True, title="X",
        start=datetime(2026, 7, 12, 0, 0, tzinfo=TZ),
        is_all_day=True,
    )
    assert _fmt_outcome_when(o) == "12/07 (dia inteiro)"


# ---------------------- _truncate ----------------------

def test_truncate_short_unchanged():
    assert _truncate("abc", 5) == "abc"


def test_truncate_exact_length_unchanged():
    assert _truncate("abcde", 5) == "abcde"


def test_truncate_long_gets_ellipsis():
    assert _truncate("abcdef", 4) == "abc…"


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
