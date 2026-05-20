"""Testes da máquina de estados de conversa.

Como rodar:
    python tests/test_conversation.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import conversation  # noqa: E402
from src.models import ExistingEvent, ParsedEvent  # noqa: E402

TZ = ZoneInfo("America/Sao_Paulo")


def _event(title: str = "Reunião") -> ParsedEvent:
    return ParsedEvent(
        title=title,
        start=datetime(2026, 5, 18, 14, 0, tzinfo=TZ),
        end=datetime(2026, 5, 18, 15, 0, tzinfo=TZ),
        is_all_day=False,
    )


def _existing(summary: str = "Almoço", event_id: str = "abc123") -> ExistingEvent:
    return ExistingEvent(
        event_id=event_id,
        summary=summary,
        start=datetime(2026, 5, 18, 12, 30, tzinfo=TZ),
        end=datetime(2026, 5, 18, 14, 30, tzinfo=TZ),
        html_link=f"https://calendar.google.com/{event_id}",
    )


# ---------------------- estados ----------------------

def test_initial_state_is_idle():
    conversation.clear()
    assert conversation.get() is None


def test_set_awaiting_decision():
    conversation.clear()
    event = _event()
    conflicts = [_existing()]
    conversation.set_awaiting_decision(event, conflicts)
    s = conversation.get()
    assert isinstance(s, conversation.AwaitingDecision)
    assert s.pending_event == event
    assert s.conflicts == conflicts


def test_set_awaiting_new_date():
    conversation.clear()
    event = _event()
    existing = _existing()
    conversation.set_awaiting_new_date(event, existing)
    s = conversation.get()
    assert isinstance(s, conversation.AwaitingNewDate)
    assert s.pending_event == event
    assert s.event_to_move == existing


def test_clear_resets_to_idle():
    conversation.set_awaiting_decision(_event(), [])
    assert conversation.get() is not None
    conversation.clear()
    assert conversation.get() is None


def test_transition_decision_then_new_date():
    """Fluxo real: usuário viu o prompt, clicou em mover → estado vira AwaitingNewDate."""
    conversation.clear()
    event = _event()
    existing = _existing()
    conversation.set_awaiting_decision(event, [existing])
    assert isinstance(conversation.get(), conversation.AwaitingDecision)
    conversation.set_awaiting_new_date(event, existing)
    s = conversation.get()
    assert isinstance(s, conversation.AwaitingNewDate)
    assert s.event_to_move.event_id == existing.event_id


def test_multiple_conflicts_preserved_in_decision():
    conversation.clear()
    event = _event()
    conflicts = [
        _existing("A", "id_a"),
        _existing("B", "id_b"),
        _existing("C", "id_c"),
    ]
    conversation.set_awaiting_decision(event, conflicts)
    s = conversation.get()
    assert isinstance(s, conversation.AwaitingDecision)
    assert len(s.conflicts) == 3
    assert [c.event_id for c in s.conflicts] == ["id_a", "id_b", "id_c"]


def test_set_overrides_previous_state():
    """set_awaiting_X sobrescreve qualquer estado anterior, sem precisar de clear."""
    conversation.set_awaiting_decision(_event(), [])
    conversation.set_awaiting_new_date(_event("Outro"), _existing())
    s = conversation.get()
    assert isinstance(s, conversation.AwaitingNewDate)
    assert s.pending_event.title == "Outro"


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
