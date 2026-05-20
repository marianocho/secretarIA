"""Bot principal: polling do Telegram, parsing, criação de eventos, fluxo
interativo de resolução de conflito.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from html import escape

from telegram import (
    Bot,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.error import NetworkError, TelegramError

from src import config, conversation, state
from src.calendar_client import (
    CreatedEvent,
    create_event,
    find_conflicts,
    update_event_times,
)
from src.models import ExistingEvent, ParseError, ParsedEvent
from src.parser import EXAMPLES_TEXT, parse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("secretarIA")


@dataclass
class _Outcome:
    """Resultado pra acumular no resumo de backlog. Não usado em modo live."""

    text: str
    success: bool
    title: str | None = None
    start: datetime | None = None
    is_all_day: bool = False
    link: str | None = None
    error_msg: str | None = None
    conflicts: list[ExistingEvent] = field(default_factory=list)


# ============================================================
# Roteamento de updates
# ============================================================


async def _process_update(update: Update, bot: Bot, send_reply: bool) -> _Outcome | None:
    """`send_reply=True` → modo live (interativo).
    `send_reply=False` → modo backlog (silencioso, cria com aviso)."""
    if update.callback_query is not None:
        if send_reply:
            await _handle_callback(update.callback_query, bot)
        else:
            await update.callback_query.answer()
        return None

    msg = update.message
    if msg is None or msg.text is None:
        return None
    if msg.from_user is None or msg.from_user.id != config.ALLOWED_TELEGRAM_USER_ID:
        log.info("ignorado: user_id=%s não autorizado",
                 msg.from_user.id if msg.from_user else None)
        return None

    text = msg.text.strip()

    if text.lower() in ("/cancelar", "/cancel"):
        conversation.clear()
        if send_reply:
            await bot.send_message(msg.chat_id, "OK, cancelado.")
        return None

    current = conversation.get()
    if isinstance(current, conversation.AwaitingNewDate) and send_reply:
        await _handle_reschedule_input(text, current, msg, bot)
        return None

    return await _handle_event_message(text, msg, bot, send_reply)


# ============================================================
# Fluxo: mensagem normal de evento
# ============================================================


async def _handle_event_message(
    text: str, msg: Message, bot: Bot, send_reply: bool
) -> _Outcome | None:
    now = datetime.now(config.TIMEZONE)
    parsed = parse(text, now)

    if isinstance(parsed, ParseError):
        error_msg = parsed.message + (f" ({parsed.detail})" if parsed.detail else "")
        if send_reply:
            await bot.send_message(
                msg.chat_id,
                f"❌ Não entendi: <b>{escape(error_msg)}</b>\n\n"
                f"<pre>{escape(EXAMPLES_TEXT)}</pre>",
                parse_mode="HTML",
            )
        return _Outcome(text=text, success=False, error_msg=error_msg)

    try:
        conflicts = find_conflicts(parsed)
    except Exception:
        log.exception("falha ao buscar conflitos (seguindo sem checar)")
        conflicts = []

    if send_reply and conflicts:
        conversation.set_awaiting_decision(parsed, conflicts)
        body, markup = _build_conflict_prompt(parsed, conflicts)
        await bot.send_message(
            msg.chat_id, body, parse_mode="HTML", reply_markup=markup,
            disable_web_page_preview=True,
        )
        return None

    try:
        created = create_event(parsed)
    except Exception as e:
        log.exception("falha ao criar evento")
        if send_reply:
            await bot.send_message(
                msg.chat_id, f"❌ Parser ok, mas Google Calendar falhou: {escape(str(e))}"
            )
        return _Outcome(text=text, success=False, error_msg=f"google: {e}")

    if send_reply:
        await bot.send_message(
            msg.chat_id,
            _format_success(parsed, created, conflicts),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    return _Outcome(
        text=text,
        success=True,
        title=parsed.title,
        start=parsed.start,
        is_all_day=parsed.is_all_day,
        link=created["html_link"],
        conflicts=conflicts,
    )


# ============================================================
# Fluxo: callback de botão
# ============================================================


async def _handle_callback(query: CallbackQuery, bot: Bot) -> None:
    chat_id = query.message.chat_id if query.message else config.ALLOWED_TELEGRAM_USER_ID
    state_now = conversation.get()

    if not isinstance(state_now, conversation.AwaitingDecision):
        await query.answer(text="Sessão expirada — manda o evento de novo.", show_alert=True)
        return

    data = query.data or ""
    pending = state_now.pending_event
    conflicts = state_now.conflicts

    if data == "create":
        await query.answer(text="Criando...")
        conversation.clear()
        try:
            created = create_event(pending)
        except Exception as e:
            log.exception("falha ao criar (create_anyway)")
            await bot.send_message(chat_id, f"❌ Falhou: {escape(str(e))}")
            return
        await bot.send_message(
            chat_id,
            _format_success(pending, created, conflicts),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    elif data == "redo":
        await query.answer(text="Manda de novo com data/hora diferente.")
        conversation.clear()
        await bot.send_message(
            chat_id,
            "OK, manda o evento de novo com data/hora diferente.",
        )

    elif data.startswith("move:"):
        try:
            idx = int(data.split(":")[1])
        except (IndexError, ValueError):
            await query.answer(text="Botão inválido.")
            return
        if idx < 0 or idx >= len(conflicts):
            await query.answer(text="Conflito não encontrado.")
            return
        target = conflicts[idx]
        conversation.set_awaiting_new_date(pending, target)
        await query.answer()
        await bot.send_message(
            chat_id,
            f"OK, manda a nova data/hora pra <b>{escape(target.summary)}</b>.\n"
            f"Exemplo: <code>18/05 16:00</code>, <code>amanhã 15:00</code>, etc.\n"
            f"Depois eu movo ele e crio o <b>{escape(pending.title)}</b> no horário original.\n\n"
            f"<i>/cancelar pra abortar.</i>",
            parse_mode="HTML",
        )

    else:
        await query.answer(text="Botão não reconhecido.")


# ============================================================
# Fluxo: nova data pra mover evento existente
# ============================================================


async def _handle_reschedule_input(
    text: str, current: "conversation.AwaitingNewDate", msg: Message, bot: Bot
) -> None:
    now = datetime.now(config.TIMEZONE)
    parsed = parse(text, now)
    if isinstance(parsed, ParseError):
        error_msg = parsed.message + (f" ({parsed.detail})" if parsed.detail else "")
        await bot.send_message(
            msg.chat_id,
            f"❌ Não entendi a nova data/hora: <b>{escape(error_msg)}</b>\n"
            f"Tenta de novo ou /cancelar.",
            parse_mode="HTML",
        )
        return

    try:
        update_event_times(
            current.event_to_move.event_id,
            parsed.start,
            parsed.end,
            parsed.is_all_day,
        )
    except Exception as e:
        log.exception("falha ao mover evento existente")
        conversation.clear()
        await bot.send_message(
            msg.chat_id,
            f"❌ Erro ao mover <b>{escape(current.event_to_move.summary)}</b>: "
            f"{escape(str(e))}\nNada foi alterado.",
            parse_mode="HTML",
        )
        return

    try:
        created = create_event(current.pending_event)
    except Exception as e:
        log.exception("existente movido, mas falhou criar o novo")
        conversation.clear()
        await bot.send_message(
            msg.chat_id,
            f"⚠️ <b>{escape(current.event_to_move.summary)}</b> foi movido pra "
            f"{parsed.start.strftime('%d/%m %H:%M')}, mas falhou criar "
            f"<b>{escape(current.pending_event.title)}</b>: {escape(str(e))}\n"
            f"Manda ele de novo se quiser.",
            parse_mode="HTML",
        )
        return

    conversation.clear()
    when_new = _format_when(current.pending_event)
    when_moved = (
        parsed.start.strftime("%d/%m") if parsed.is_all_day
        else parsed.start.strftime("%d/%m %H:%M")
    )
    await bot.send_message(
        msg.chat_id,
        f"🔄 <b>{escape(current.event_to_move.summary)}</b> movido pra {when_moved}\n"
        f"✅ <b>{escape(current.pending_event.title)}</b> criado — {when_new}\n"
        f'<a href="{escape(created["html_link"])}">abrir no calendar</a>',
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ============================================================
# Formatadores
# ============================================================


def _format_success(
    event: ParsedEvent, created: CreatedEvent, conflicts: list[ExistingEvent]
) -> str:
    when = _format_when(event)
    lines = [f"✅ <b>{escape(event.title)}</b> — {when}"]
    if event.location:
        lines.append(f"📍 {escape(event.location)}")
    if event.notes:
        lines.append(f"📝 {escape(event.notes)}")
    if conflicts:
        lines.append("")
        lines.append(_format_conflict_block(conflicts))
    lines.append(f'<a href="{escape(created["html_link"])}">abrir no calendar</a>')
    return "\n".join(lines)


def _format_conflict_block(conflicts: list[ExistingEvent]) -> str:
    n = len(conflicts)
    if n == 1:
        c = conflicts[0]
        return (
            f"⚠️ Conflito com <b>{escape(c.summary)}</b> "
            f"({_format_existing_when(c)})"
        )
    shown = conflicts[:5]
    lines = [f"⚠️ Conflito com {n} eventos:"]
    for c in shown:
        lines.append(f"  • {escape(c.summary)} ({_format_existing_when(c)})")
    if n > 5:
        lines.append(f"  ...e mais {n - 5}")
    return "\n".join(lines)


def _build_conflict_prompt(
    event: ParsedEvent, conflicts: list[ExistingEvent]
) -> tuple[str, InlineKeyboardMarkup]:
    when = _format_when(event)
    lines = [f"⚠️ <b>{escape(event.title)}</b> ({when}) conflita com:"]
    for c in conflicts:
        lines.append(f"  • {escape(c.summary)} ({_format_existing_when(c)})")
    lines.append("")
    lines.append("O que fazer?")
    body = "\n".join(lines)

    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("✅ Criar mesmo assim", callback_data="create")]
    ]
    for i, c in enumerate(conflicts):
        label = _truncate(c.summary, 25)
        buttons.append([
            InlineKeyboardButton(
                f"🔄 Mover '{label}' ({c.start.strftime('%H:%M')})",
                callback_data=f"move:{i}",
            )
        ])
    buttons.append(
        [InlineKeyboardButton("↩️ Refazer evento novo", callback_data="redo")]
    )
    return body, InlineKeyboardMarkup(buttons)


def _format_when(event: ParsedEvent) -> str:
    if event.is_all_day:
        return event.start.strftime("%d/%m/%Y (dia inteiro)")
    same_day = event.start.date() == event.end.date()
    if same_day:
        return event.start.strftime("%d/%m/%Y %H:%M") + event.end.strftime("–%H:%M")
    return f"{event.start.strftime('%d/%m %H:%M')} → {event.end.strftime('%d/%m %H:%M')}"


def _format_existing_when(c: ExistingEvent) -> str:
    same_day = c.start.date() == c.end.date()
    if same_day:
        return c.start.strftime("%H:%M") + c.end.strftime("–%H:%M")
    return f"{c.start.strftime('%d/%m %H:%M')} → {c.end.strftime('%d/%m %H:%M')}"


def _format_backlog_summary(outcomes: list[_Outcome]) -> str:
    successes = [o for o in outcomes if o.success]
    failures = [o for o in outcomes if not o.success]
    total = len(outcomes)
    lines = [f"📬 <b>Backlog processado</b> ({total} mensage{'m' if total == 1 else 'ns'})"]

    if successes:
        lines.append("")
        lines.append(f"✅ Criados ({len(successes)}):")
        for o in successes:
            when = _fmt_outcome_when(o)
            assert o.link is not None and o.title is not None
            warn = " ⚠️" if o.conflicts else ""
            lines.append(
                f'• <a href="{escape(o.link)}">{escape(o.title)}</a> — {when}{warn}'
            )

    if failures:
        lines.append("")
        lines.append(f"❌ Erros ({len(failures)}):")
        for o in failures:
            lines.append(f"• <i>{escape(o.text[:60])}</i> — {escape(o.error_msg or 'desconhecido')}")

    return "\n".join(lines)


def _fmt_outcome_when(o: _Outcome) -> str:
    assert o.start is not None
    if o.is_all_day:
        return o.start.strftime("%d/%m (dia inteiro)")
    return o.start.strftime("%d/%m %H:%M")


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


# ============================================================
# Loop principal
# ============================================================


_ALLOWED_UPDATE_TYPES = ["message", "callback_query"]


async def _drain_backlog(bot: Bot, last_id: int | None) -> int | None:
    offset = (last_id + 1) if last_id is not None else None
    log.info("buscando backlog (offset=%s)...", offset)
    updates = await bot.get_updates(
        offset=offset, timeout=0, allowed_updates=_ALLOWED_UPDATE_TYPES
    )
    if not updates:
        log.info("sem backlog")
        return last_id

    log.info("backlog: %d updates", len(updates))
    outcomes: list[_Outcome] = []
    for update in updates:
        outcome = await _process_update(update, bot, send_reply=False)
        if outcome is not None:
            outcomes.append(outcome)

    if outcomes:
        summary = _format_backlog_summary(outcomes)
        await bot.send_message(
            config.ALLOWED_TELEGRAM_USER_ID,
            summary,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    return updates[-1].update_id


async def _live_loop(bot: Bot, last_id: int | None) -> None:
    log.info("entrando em modo polling. Ctrl+C pra parar.")
    while True:
        try:
            offset = (last_id + 1) if last_id is not None else None
            updates = await bot.get_updates(
                offset=offset, timeout=30, allowed_updates=_ALLOWED_UPDATE_TYPES
            )
        except NetworkError as e:
            log.warning("network error: %s. Retry em 5s...", e)
            await asyncio.sleep(5)
            continue
        except TelegramError:
            log.exception("erro do Telegram. Retry em 10s...")
            await asyncio.sleep(10)
            continue

        for update in updates:
            try:
                await _process_update(update, bot, send_reply=True)
            except Exception:
                log.exception("erro ao processar update_id=%s", update.update_id)
            last_id = update.update_id
            state.save_last_update_id(last_id)


async def main() -> None:
    bot = Bot(config.TELEGRAM_BOT_TOKEN)
    me = await bot.get_me()
    log.info("conectado como @%s (id=%s)", me.username, me.id)

    last_id = state.load_last_update_id()
    new_last_id = await _drain_backlog(bot, last_id)
    if new_last_id is not None and new_last_id != last_id:
        state.save_last_update_id(new_last_id)

    await _live_loop(bot, new_last_id)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("encerrado pelo usuário")
