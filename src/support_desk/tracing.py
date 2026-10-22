"""Run tracing: one row per agent turn plus one row per tool call, stored in Postgres."""
import json
import time
import uuid
import sys
from contextlib import contextmanager

from psycopg.types.json import Jsonb

from support_desk.db import connect
from support_desk.redact import redact

# USD per 1M tokens (input, output). Update if COPILOT_MODEL changes.
PRICING = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}

def cost(model: str, in_tok: int, out_tok: int) -> float:
    pi, po = PRICING.get(model, (0.0, 0.0))
    return (in_tok * pi + out_tok * po) / 1_000_000

def _jsonb(value):
    """Redact, then store as JSONB (parsed if it is JSON text, else wrapped as {"text": ...})."""
    if not isinstance(value, str):
        value = json.dumps(value, default=str)
    value = redact(value)
    try:
        return Jsonb(json.loads(value))
    except ValueError:
        return Jsonb({"text": value})

class Trace:
    def __init__(self, ticket_id=None, model="", eval_run_id=None):
        self.run_id = uuid.uuid4()
        self.ticket_id, self.model, self.eval_run_id = ticket_id, model, eval_run_id
        self.in_tok = self.out_tok = self.iterations = 0
        self.tool_calls: list[dict] = []
        self.answer: str | None = None
        self.error: str | None = None

    def add_usage(self, usage) -> None:
        """Call once per model response."""
        self.iterations += 1
        if usage:
            self.in_tok += usage.prompt_tokens or 0
            self.out_tok += usage.completion_tokens or 0

    def add_tool_call(self, name, args, result, latency_ms, is_error=False) -> None:
        self.tool_calls.append({
            "seq": len(self.tool_calls), "name": name, "args": args,
            "result": result, "latency_ms": latency_ms, "is_error": is_error,
        })

def _save(t: Trace, latency_ms: float) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO traces.runs
               (run_id, ticket_id, eval_run_id, model, input_tokens, output_tokens,
                cost_usd, latency_ms, n_tool_calls, n_iterations, final_answer, error)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (t.run_id, t.ticket_id, t.eval_run_id, t.model, t.in_tok, t.out_tok,
             cost(t.model, t.in_tok, t.out_tok), latency_ms, len(t.tool_calls),
             t.iterations, redact(t.answer or ""), t.error),
        )
        if t.tool_calls:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO traces.tool_calls
                       (run_id, seq, name, args, result, latency_ms, is_error)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    [(t.run_id, r["seq"], r["name"], _jsonb(r["args"]), _jsonb(r["result"]),
                      r["latency_ms"], r["is_error"]) for r in t.tool_calls],
                )

@contextmanager
def traced_run(ticket_id=None, model="", eval_run_id=None):
    t, t0 = Trace(ticket_id, model, eval_run_id), time.perf_counter()
    try:
        yield t
    except Exception as e:
        t.error = repr(e)
        raise
    finally:
        try:
            _save(t, (time.perf_counter() - t0) * 1000)
        except Exception as e: # tracing must never break the agent
            print(f"[tracing] failed to save run: {e!r}", file=sys.stderr)
