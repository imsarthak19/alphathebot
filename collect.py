#!/usr/bin/env python3
"""Sends eval questions (evals/questions.json) to student Telegram bots and
records each student's answer, one file per (student, question), under
data/<slug>/<question_id>.json.

Processes ONE QUESTION AT A TIME across the whole class ("question-major"),
not one student's whole question set at a time - for large classes this can
take days, and question-major means no student sees question 2's content
before every student has had their turn at question 1, bounding leakage
across the class.

Within a question, students are processed concurrently (bounded by
--concurrency, throttled by --stagger-seconds between conversation starts)
so wall-clock time isn't students x timeout - safer under Telegram's
anti-spam heuristics because new first-contacts trickle in rather than
bursting.

Every attempt records one JSON file per (student, question) with a `status`:
    ok       - got replies (grading decides correctness)
    timeout  - message sent, no reply within timeout_seconds (student's bot)
    bad_bot  - username unresolvable / not a bot (student's problem)
    error    - our-side/unexpected failure (network, etc.), captured with a
               reason and RE-ATTEMPTED on the next run
timeout_seconds is the budget for the whole (possibly multi-turn) exchange.

Resumable at any scale: a terminal outcome (ok/timeout/bad_bot) is skipped on
re-run; only `error` files are retried. The run never stops for a per-student
failure - it only pauses for Telegram rate limiting: FloodWait is retried in
place with exponential backoff; a persistent PeerFlood, after backoff, stops
the run for manual @SpamBot verification, after which you just re-run.

Usage:
    python collect.py --students students.csv
"""
import argparse
import asyncio
import csv
import json
import os
import re
import sys
from pathlib import Path
from string import Template

from dotenv import load_dotenv
load_dotenv()

from telethon import TelegramClient
from telethon.errors import (FloodWaitError, PeerFloodError,
                              UsernameInvalidError, UsernameNotOccupiedError)
from telethon.sessions import StringSession

# Rate-limit backoff knobs (seconds). FloodWait is retried in place; a
# persistent PeerFlood pauses the whole run before stopping for @SpamBot.
BACKOFF_BASE = 30
FLOOD_RETRIES = 3
FLOOD_MAX_WAIT = 600
PEERFLOOD_RETRIES = 5
PEERFLOOD_MAX_WAIT = 3600

TERMINAL = {"ok", "timeout", "bad_bot"}  # recorded outcomes not retried on re-run


def slugify(email):
    return re.sub(r"[^a-zA-Z0-9]+", "_", email.strip().lower()).strip("_")


def render(text, vars_):
    """Fill $name placeholders with this student's vars (as JSON literals).
    substitute() raises KeyError if the text needs a var we didn't generate -
    fail loudly here, before anything is sent to a bot."""
    try:
        return Template(text).substitute({k: json.dumps(v) for k, v in vars_.items()})
    except KeyError as e:
        raise SystemExit(f"message needs var {e} not generated for this student: {text!r}")


def result_path(data_dir, email, question_id):
    d = Path(data_dir) / slugify(email)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{question_id}.json"


def write_result_atomic(path, result):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2))
    tmp.rename(path)


async def _converse(client, bot, messages, timeout, email, qid):
    """Run the exchange and classify the outcome as (status, detail, sent,
    replies). Every failure is captured except PeerFloodError, which is
    account-level and re-raised to pause the whole run."""
    for attempt in range(FLOOD_RETRIES):
        sent, replies = [], []
        try:
            async with client.conversation(bot, timeout=timeout) as conv:
                for msg in messages:
                    await conv.send_message(msg)
                    sent.append(msg)
                    replies.append((await conv.get_response()).raw_text)
            return "ok", None, sent, replies
        except asyncio.TimeoutError:
            return "timeout", "no reply within budget", sent, replies
        except (UsernameInvalidError, UsernameNotOccupiedError, ValueError) as e:
            return "bad_bot", str(e), sent, replies
        except PeerFloodError:
            raise  # account-level rate limit -> handled by run_wave_resilient
        except FloodWaitError as e:
            if e.seconds > FLOOD_MAX_WAIT:  # don't wedge a slot; retry on next run
                return "error", f"FloodWait {e.seconds}s exceeds cap", sent, replies
            wait = e.seconds + BACKOFF_BASE * 2 ** attempt
            print(f"[{email}] {qid}: FloodWait {e.seconds}s, backing off {wait}s ({attempt + 1}/{FLOOD_RETRIES})")
            await asyncio.sleep(wait)
        except Exception as e:  # our-side/unexpected -> capture, retry on next run
            return "error", f"{type(e).__name__}: {e}", sent, replies
    return "error", "FloodWait retries exhausted", sent, replies


async def run_one(client, row, question, vars_, data_dir, sem):
    email = row["email"]
    out_path = result_path(data_dir, email, question["id"])
    if out_path.exists() and json.loads(out_path.read_text()).get("status") in TERMINAL:
        return  # terminal outcome recorded - skip; only "error" is retried

    messages = [render(t, vars_) for t in question["messages"]]  # raises before any send if a placeholder is unfilled
    async with sem:
        status, detail, sent, replies = await _converse(
            client, row["telegram_bot_username"], messages, question.get("timeout_seconds", 300),
            email, question["id"])

    result = {"status": status, "vars": vars_, "sent": sent, "replies": replies}
    if detail:
        result["detail"] = detail
    write_result_atomic(out_path, result)
    print(f"[{email}] {question['id']}: {status} ({len(replies)} replies)")


async def run_question_wave(client, students, question, inputs_q, data_dir, concurrency, stagger_seconds):
    sem = asyncio.Semaphore(concurrency)
    tasks = []
    for row in students:
        tasks.append(asyncio.create_task(
            run_one(client, row, question, inputs_q[row["email"]], data_dir, sem)))
        await asyncio.sleep(stagger_seconds)  # throttles how fast new bots get first-contacted

    for coro in asyncio.as_completed(tasks):
        try:
            await coro
        except PeerFloodError:
            for t in tasks:
                t.cancel()
            raise  # to run_wave_resilient, which backs off and retries the wave


async def run_wave_resilient(client, students, question, inputs_q, data_dir, concurrency, stagger_seconds):
    """Run a question wave, absorbing account-level PeerFlood rate limiting with
    exponential backoff. Re-running the wave naturally resumes (done students
    are skipped). Only a PeerFlood that persists past the retries stops the run."""
    for attempt in range(PEERFLOOD_RETRIES):
        try:
            await run_question_wave(client, students, question, inputs_q,
                                    data_dir, concurrency, stagger_seconds)
            return
        except PeerFloodError:
            wait = min(BACKOFF_BASE * 2 ** attempt, PEERFLOOD_MAX_WAIT)
            print(f"PeerFlood (account rate-limited). Backing off {wait}s, "
                  f"attempt {attempt + 1}/{PEERFLOOD_RETRIES}...")
            await asyncio.sleep(wait)
    sys.exit("FATAL: still PeerFlood-limited after backoff. Verify the account via @SpamBot in "
             "Telegram, then re-run - recorded students (and our-side 'error' retries) are handled correctly.")


async def main_async(students, questions, inputs, data_dir, concurrency, stagger_seconds):
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    client = TelegramClient(StringSession(os.environ["TELEGRAM_SESSION_STRING"]), api_id, api_hash)
    async with client:
        for question in questions:  # question-major: everyone finishes Q_n before Q_n+1 starts
            print(f"=== question '{question['id']}': {len(students)} students ===")
            await run_wave_resilient(client, students, question, inputs[question["id"]],
                                     data_dir, concurrency, stagger_seconds)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--students", required=True, help="roster CSV: email,github_url,telegram_bot_username")
    ap.add_argument("--questions", default="evals/questions.json")
    ap.add_argument("--inputs", default="inputs.json", help="from generate.py; run it first")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--concurrency", type=int, default=5, help="max simultaneous bot conversations")
    ap.add_argument("--stagger-seconds", type=float, default=2.0,
                     help="min delay between starting new conversations")
    args = ap.parse_args()

    students = list(csv.DictReader(open(args.students, newline="")))
    questions = json.load(open(args.questions))
    inputs = json.load(open(args.inputs))

    missing = [r["email"] for q in questions for r in students if r["email"] not in inputs.get(q["id"], {})]
    if missing:
        sys.exit(f"{len(missing)} (student, question) pairs missing from {args.inputs} - "
                 f"run generate.py first. e.g. {missing[:3]}")

    asyncio.run(main_async(students, questions, inputs, args.data_dir, args.concurrency, args.stagger_seconds))


if __name__ == "__main__":
    main()
