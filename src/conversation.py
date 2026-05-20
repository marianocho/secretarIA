"""Máquina de estados da conversa (1 usuário, in-memory).

Estados possíveis:
- None (IDLE)
- AwaitingDecision: usuário viu o prompt de conflito, esperando ele clicar
  num botão.
- AwaitingNewDate: usuário escolheu mover um evento existente; esperando
  ele mandar a nova data/hora por mensagem texto.

Em memória de propósito: se o bot reiniciar, conversa abandonada. Usuário
reenvia o evento. Persistir em disco adicionaria complexidade que não vale
o ganho marginal pra single-user.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.models import ExistingEvent, ParsedEvent


@dataclass
class AwaitingDecision:
    pending_event: ParsedEvent
    conflicts: list[ExistingEvent]


@dataclass
class AwaitingNewDate:
    pending_event: ParsedEvent
    event_to_move: ExistingEvent


State = AwaitingDecision | AwaitingNewDate | None

_state: State = None


def get() -> State:
    return _state


def set_awaiting_decision(event: ParsedEvent, conflicts: list[ExistingEvent]) -> None:
    global _state
    _state = AwaitingDecision(pending_event=event, conflicts=conflicts)


def set_awaiting_new_date(event: ParsedEvent, event_to_move: ExistingEvent) -> None:
    global _state
    _state = AwaitingNewDate(pending_event=event, event_to_move=event_to_move)


def clear() -> None:
    global _state
    _state = None
