# HaikaruTrade — News/Risk Context Backend

This is the Python side of the backend/EA split we designed: this code is
the "otak" (brain) that researches context and writes a signal file; the
`HaikaruTrade.mq5` EA is the "tangan" (hand) that reads it, validates it,
and is always free to say no.

## What this does — and deliberately does NOT do

This pipeline answers **"is it safe to trade right now"**, not **"which way
should we trade"**. There's no `direction` / buy-sell field anywhere in the
output. That's intentional: no LLM has genuine forward-looking market edge,
and asking one to roleplay as a top investor doesn't create that edge — it
just makes an ungrounded guess sound more confident. Real directional edge
has to come from the statistically validated strategy research (mean
reversion / stat-arb, Fase 2 on the roadmap), which isn't built yet. This
backend is a **risk filter** that the eventual strategy signal will need to
pass through, not a signal source itself.

## Pipeline

1. **`economic_calendar.py`** — checks a manually-maintained schedule for
   high-impact events. No AI involved; this is scheduled data, not a
   research question.
2. **`news_analyst.py`** (Stage 1, `gemma-4-26b-a4b-it`) — Google Search
   grounded summary of current news/sentiment. Returns tone + notable
   events, never a prediction.
3. **`financial_reviewer.py`** (Stage 2, `gemma-4-31b-it`, high thinking) —
   checklist-based sanity check: does the news context contradict the
   calendar status, is anything severe enough to warrant an unscheduled
   pause. Not asked to predict price, ever.
4. **`signal_writer.py`** — atomic write of the combined result to
   `signal.json`, which the EA polls on its `OnTimer`.

`orchestrator.py` runs one full cycle. Schedule it — don't call it every
60 seconds. Every 15–30 minutes is plenty; news tone doesn't change
minute to minute, and tighter polling just burns quota.

## Where this lives on your machine

Drop this whole folder in as `E:\ResearchMT5\python_backend\` - the Python
side doesn't care where its own .py files sit, only orchestrator.py's
default signal path matters for the EA side (see below).

## Setup

```bash
pip install -r requirements.txt
cp keys.example.json keys.json          # fill in real API keys
cp calendar_events.example.json calendar_events.json   # fill in real dates
```

Each entry in `keys.json` must be a key from a **separate** Google Cloud
project — Google enforces RPM/TPM/RPD per project, not per key, so keys
sharing a project share one quota bucket and rotating between them buys
nothing.

Run one cycle manually to check everything's wired up:

```bash
python orchestrator.py
```

Then point Windows Task Scheduler (or equivalent) at `orchestrator.py` on
your chosen interval, and point `SIGNAL_PATH` in `orchestrator.py` at the
file path your EA actually reads.

## Reading signal.json from the EA side

MQL5's FileOpen() is sandboxed - it cannot open an arbitrary path like an E:
drive folder directly. This backend writes signal.json into MT5's shared
Common\Files folder instead (a stable path with no per-terminal hash in it),
and the EA must open it with the FILE_COMMON flag to match:

```mql5
int handle = FileOpen("signal.json", FILE_READ|FILE_TXT|FILE_COMMON);
if(handle != INVALID_HANDLE)
  {
   string line = "";
   while(!FileIsEnding(handle))
      line += FileReadString(handle);
   FileClose(handle);
   // parse `line` as JSON, check generated_at_unix freshness before
   // trusting safe_to_trade - this is the "penjaga akhir" check from
   // our earlier design, do not skip it
  }
```

## A constraint worth knowing about

The Gemini API rejects combining the `google_search` tool with enforced
`response_schema` in the same call (confirmed via a live 400
`INVALID_ARGUMENT` error while building this: *"controlled generation is
not supported with google_search tool"*). That's why `news_analyst.py`
asks for a JSON tail in free text and parses it with regex instead of using
`response_schema` directly — and why it fails safe to `tone: "unknown"`
if that parse ever comes up empty, rather than raising and breaking the
cycle.

## Not built yet

- The dashboard (quota usage, signal history, equity/drawdown charts) —
  next after this is confirmed working end to end.
- The actual directional strategy (mean reversion / stat-arb) that will
  eventually consume `signal.json`'s `safe_to_trade` flag as a gate.
- A real economic calendar data source — `calendar_events.json` is
  currently hand-maintained placeholder data.
