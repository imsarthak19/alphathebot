# TDS P1 — Telegram bot grading pipeline

Sends a fixed set of questions to each student's Telegram bot and grades the
replies, at class scale. Three decoupled stages — only `collect.py` touches
Telegram:

```
questions.json                    # messages + recipes + answer spec
   │  generate.py   (no network)
   ├─▶ inputs.json  public   { qid: { email: {<vars>} } }   per-student inputs
   └─▶ key.json     private  { qid: { email: <answer> } }   per-student answers
   │  collect.py    (Telegram: render, send, record raw)
   └─▶ data/<slug>/<qid>.json    { status, vars, sent, replies }
   │  grade.py      (no network: extract reply, compare to key.json)
   └─▶ data/<slug>/grade.json
```

`inputs.json`/`data/`/`key.json` are git-ignored; `key.json` is the private
answer key — never publish it.

## Setup

```
uv sync            # or: pip install -r requirements.txt
```

Bots can't message bots, so the grader logs in as a Telegram **user account**.
Copy `.env.example` to `.env` and fill it in (each step is in its comments):

- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — https://my.telegram.org → *API
  development tools* → create an app.
- `TELEGRAM_SESSION_STRING` — run `python3 login.py` once in a real terminal
  (asks for your phone + the login code Telegram texts you); paste what it prints.
- `BOT_TOKEN` — only for the test bot below: message `@BotFather` → `/newbot`.

Use a number dedicated to grading. Roster is a CSV:
`email,github_url,telegram_bot_username`.

To test the pipeline without real students, run `python3 test_bot/fake_student_bot.py`
in its own terminal (needs `BOT_TOKEN`) and put its `@username` in a one-row roster.

## Run

```
python3 generate.py --students students.csv    # -> inputs.json, key.json
python3 collect.py  --students students.csv    # the only Telegram step
python3 grade.py    --students students.csv    # -> data/<slug>/grade.json
```

`collect.py` is resumable and safe to re-run: it records a `status` per attempt
— `ok` / `timeout` / `bad_bot` (terminal, skipped) or `error` (our-side,
retried). It never stops for a per-student failure, only for Telegram rate
limits (FloodWait → backoff-and-retry; persistent PeerFlood → stop, verify via
`@SpamBot`, re-run). Inputs are drawn deterministically from `email + question
id`, so runs are reproducible. Tune `--concurrency` (5) / `--stagger-seconds`
(2) to stay under Telegram's anti-spam limits.

## Answer contract

A bot's **final reply must be exactly one JSON object, nothing else** — e.g.
`{"state": "Assam"}`. Prose around it is a `format_error`.

## Adding a question — edit `evals/questions.json` only

```json
{
  "id": "flow_rate_forecast",
  "timeout_seconds": 300,
  "randomize":     { "inputs": "rng.sample(range(10, 500), 5)" },
  "messages": ["Forecast for these inputs: $inputs. Reply with ONLY {\"values\": [<numbers>]}."],
  "expected_code": "{\"values\": [round(x * 1.02, 2) for x in inputs]}"
}
```

`randomize` draws per-student inputs (seeded `rng`, plus `math`/`statistics`);
omit it for questions with no inputs. `messages` uses `$name` placeholders
(literal `$` → `$$`); a list is a multi-turn exchange. Give the answer as a
static `expected`, or `expected_code` — a formula over that student's `vars`.
A new *match type* (e.g. numeric tolerance) is the only thing needing code: add
a branch to `grade()` in `grade.py`. Grading is exact-match today.
