#!/usr/bin/env python3
"""Throwaway bot for testing collect.py end-to-end. Simulates a minimal
"student agent": on any message it waits a couple seconds (simulating
thinking) then replies with a FINAL_ANSWER matching whatever it was asked -
not a real analysis, just enough to prove the whole pipeline (send, wait,
extract, grade) actually works against a live Telegram bot.

Leave this running in its own terminal while you run collect.py elsewhere.

Usage:
    TELEGRAM_API_ID=... TELEGRAM_API_HASH=... BOT_TOKEN=... python3 test_bot/fake_student_bot.py
"""
import asyncio
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # load TELEGRAM_API_ID/TELEGRAM_API_HASH from .env if present
from telethon import TelegramClient, events


async def main():
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    bot_token = os.environ["BOT_TOKEN"]

    session_path = Path(__file__).parent / "fake_student_bot_session"
    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.start(bot_token=bot_token)
    me = await client.get_me()
    print(f"fake student bot @{me.username} is running - Ctrl+C to stop")

    @client.on(events.NewMessage)
    async def handler(event):
        text = event.raw_text or ""
        lower = text.lower()
        await asyncio.sleep(2)

        if "maternal mortality" in lower:
            await event.respond(json.dumps({"state": "Assam"}))
        elif "forecast flow rate for these inputs" in lower:
            match = re.search(r"\[([^\]]+)\]", text)
            inputs = [float(x) for x in match.group(1).split(",")] if match else []
            forecast = [round(v * 1.02, 2) for v in inputs]
            await event.respond(json.dumps({"values": forecast}))
        elif "build a model to forecast" in lower:
            await event.respond("Model built and ready.")
        else:
            await event.respond("OK")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
