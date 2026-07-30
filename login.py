"""One-time interactive login for the grader's Telegram account.

Run this yourself in a real terminal (not through an assistant) since it
asks for your phone number and the login code Telegram texts you:

    python3 login.py

Reads TELEGRAM_API_ID/TELEGRAM_API_HASH from .env if present, otherwise
prompts for them. Prints a session string - put it in your environment (or
.env) as TELEGRAM_SESSION_STRING and you won't need to log in again.
"""
import asyncio
import os

from dotenv import load_dotenv
load_dotenv()

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(os.environ.get("TELEGRAM_API_ID") or input("api_id: "))
    api_hash = os.environ.get("TELEGRAM_API_HASH") or input("api_hash: ")
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        await client.start()
        print("\nLogin successful. Save this as TELEGRAM_SESSION_STRING:\n")
        print(client.session.save())


if __name__ == "__main__":
    asyncio.run(main())
