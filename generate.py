#!/usr/bin/env python3
"""Generate per-student inputs and the private answer key - all BEFORE any
Telegram contact. This is the ONLY place the answer formula runs; collect.py
renders these vars into the question templates and sends, grading.py compares.

Writes two files:

    inputs.json (public):  { "<qid>": { "<email>": {<vars>} } }
    key.json  (private):   { "<qid>": { "<email>": <expected answer> } }

`vars` are drawn deterministically from the student's email + question id, so
re-running is stable and collect.py/grading.py see the same values. The
expected answer is a static `expected` from questions.json, or `expected_code`
evaluated over that student's vars (so per-student answers are computed here).

Usage: python3 generate.py --students students.csv
"""
import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from pathlib import Path


def generate_vars(question, email):
    """The `randomize` snippets are trusted config from questions.json."""
    recipe = question.get("randomize", {})
    if not recipe:
        return {}
    rng = random.Random(int(hashlib.sha256(f"{email}:{question['id']}".encode()).hexdigest(), 16))
    return {name: eval(code, {"rng": rng, "math": math, "statistics": statistics})
            for name, code in recipe.items()}


def compute_expected(question, vars_):
    """Static `expected`, or `expected_code` evaluated over this student's
    vars. Trusted config from questions.json; builtins like round() come free."""
    if "expected_code" in question:
        return eval(question["expected_code"], {"math": math, "statistics": statistics, **vars_})
    return question["expected"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--students", required=True, help="roster CSV: email,github_url,telegram_bot_username")
    ap.add_argument("--questions", default="evals/questions.json")
    ap.add_argument("--out", default="inputs.json")
    ap.add_argument("--key", default="key.json")
    args = ap.parse_args()

    students = list(csv.DictReader(open(args.students, newline="")))
    questions = json.load(open(args.questions))

    inputs, key = {}, {}
    for q in questions:
        inputs[q["id"]], key[q["id"]] = {}, {}
        for row in students:
            vars_ = generate_vars(q, row["email"])
            inputs[q["id"]][row["email"]] = vars_
            key[q["id"]][row["email"]] = compute_expected(q, vars_)

    Path(args.out).write_text(json.dumps(inputs, indent=2))
    Path(args.key).write_text(json.dumps(key, indent=2))
    print(f"wrote {args.out} + {args.key}: {len(questions)} questions x {len(students)} students")


if __name__ == "__main__":
    main()
