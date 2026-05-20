"""Descobre seu chat_id no Telegram (setup script, roda 1x).

Uso:
    1. Configura TELEGRAM_BOT_TOKEN no .env
    2. Manda qualquer mensagem pro seu bot pelo Telegram
    3. python -m src.find_chat_id
    4. Cola o id que aparece em ALLOWED_TELEGRAM_USER_ID no .env

Importante: este script lê o token direto do .env (sem importar src.config)
pra evitar exigir ALLOWED_TELEGRAM_USER_ID estar definido — afinal o objetivo
do script é descobrir esse valor.

Como efeito colateral, depois de mostrar os ids o script também marca as
mensagens vistas como entregues (ack), pra que o bot não tente parsear elas
como eventos quando subir.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Bot

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


async def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não definido no .env")

    bot = Bot(token)
    me = await bot.get_me()
    print(f"Bot: @{me.username}")
    print("Buscando mensagens recentes...\n")

    updates = await bot.get_updates(timeout=0)
    if not updates:
        print("Nenhuma mensagem encontrada.")
        print("Manda qualquer mensagem pro seu bot pelo Telegram e roda de novo.")
        return

    seen: dict[int, str] = {}
    for u in updates:
        if u.message and u.message.from_user:
            user = u.message.from_user
            label = (user.first_name or "") + " " + (user.last_name or "")
            label = label.strip() or "(sem nome)"
            if user.username:
                label += f" @{user.username}"
            seen[user.id] = label

    print("Ids encontrados:")
    for uid, label in seen.items():
        print(f"  {uid}  →  {label}")

    print("\nCola seu id em ALLOWED_TELEGRAM_USER_ID no .env.\n")

    await bot.get_updates(offset=updates[-1].update_id + 1, timeout=0)
    print(f"({len(updates)} update(s) marcados como entregues.)")


if __name__ == "__main__":
    asyncio.run(main())
