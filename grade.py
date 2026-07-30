#!/usr/bin/env python3
"""Grade every student from already-collected data (data/<slug>/*.json,
written by collect.py) against the private answer key (key.json, written by
generate.py). No Telegram, no answer formula here - just extract the reply
and compare - so it's freely re-runnable any time without waiting on a bot.

Writes data/<slug>/grade.json per student: a list of
{question_id, status, correct, detail} rows.

Minimal for now: exact match. Extend later (tolerance, etc.) without
re-collecting or re-generating anything.

Usage: python3 grade.py --students students.csv
"""
import argparse
import csv
import json
import re
from pathlib import Path


def slugify(email):
    return re.sub(r"[^a-zA-Z0-9]+", "_", email.strip().lower()).strip("_")


def extract_answer(replies):
    """The student's final reply must be exactly one JSON object (no prose)."""
    if not replies:
        return None
    try:
        return json.loads(replies[-1].strip())
    except json.JSONDecodeError:
        return None


def grade(collected, expected):
    """Returns (correct: bool, detail: str)."""
    if collected.get("status") != "ok":
        return False, collected.get("status", "not_attempted")
    answer = extract_answer(collected.get("replies", []))
    if answer is None:
        return False, "format_error"
    ok = answer == expected
    return ok, ("ok" if ok else f"expected {expected}, got {answer}")


def grade_student(email, questions, key, data_dir):
    rows = []
    for q in questions:
        path = Path(data_dir) / slugify(email) / f"{q['id']}.json"
        if not path.exists():
            rows.append({"question_id": q["id"], "status": "not_attempted", "correct": False})
            continue

        collected = json.loads(path.read_text())
        correct, detail = grade(collected, key[q["id"]][email])
        rows.append({"question_id": q["id"], "status": collected.get("status"),
                     "correct": correct, "detail": detail})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--students", required=True, help="roster CSV: email,github_url,telegram_bot_username")
    ap.add_argument("--questions", default="evals/questions.json")
    ap.add_argument("--key", default="key.json", help="from generate.py")
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    questions = json.load(open(args.questions))
    key = json.load(open(args.key))

    for row in csv.DictReader(open(args.students, newline="")):
        email = row["email"]
        rows = grade_student(email, questions, key, args.data_dir)
        out_path = Path(args.data_dir) / slugify(email) / "grade.json"
        out_path.write_text(json.dumps(rows, indent=2))
        n_correct = sum(1 for r in rows if r["correct"] is True)
        print(f"[{email}] {n_correct}/{len(rows)} correct -> {out_path}")


if __name__ == "__main__":
    main()
