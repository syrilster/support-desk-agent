# Support Desk Agent

Local learning project for agentic AI architecture.

## Prerequisites
- Python 3.12
- Docker (e.g. Rancher Desktop with the `dockerd (moby)` engine)
- An OpenAI API key

## Setup

```bash
# 1. Python environment
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt

# 2. Config
cp .env.example .env
# edit .env: set OPENAI_API_KEY (DATABASE_URL, COPILOT_MODEL and the pipeline
# model vars have working defaults)

# 3. Postgres (first time only)
docker run -d --name support-db \
  -e POSTGRES_USER=support \
  -e POSTGRES_PASSWORD=support \
  -e POSTGRES_DB=support \
  -p 5432:5432 \
  -v support_pgdata:/var/lib/postgresql/data \
  postgres:16

# 4. Load schema + sample data (safe to re-run; it drops and recreates the tables)
docker exec -i support-db psql -U support -d support -v ON_ERROR_STOP=1 < src/db/seed.sql
```

Day to day: `docker start support-db` / `docker stop support-db`.

## Run the agent

From the project root, with the venv active and Postgres running:

```bash
# Single agent (MCP client; it starts the server itself)
PYTHONPATH=src python -m support_desk.agent_mcp

# Multi-agent pipeline (Day 6)
PYTHONPATH=src python -m support_desk.pipeline_cli "My email is alice@example.com, where is my order?"
```

Both entry points are interactive when run without arguments; type `quit` to exit. Do not start the MCP server separately —
both entry points launch it. See [Day 5](#day-5-mcp-server-and-client) and
[Day 6](#day-6-multi-agent-pipeline).

## Day 1: API basics and a first tool

```bash
PYTHONPATH=src python -m support_desk.day1_hello   # basic call, usage, finish reason
PYTHONPATH=src python -m support_desk.day1_tool    # tool call -> tool result round trip
```

## Day 2: Agent loop with real data

Interactive CLI (keeps conversation history across turns):

```bash
PYTHONPATH=src python -m support_desk.agent
```

One-shot:

```bash
PYTHONPATH=src python -m support_desk.agent "My email is alice@example.com, where is my order?"
```

Each tool call prints as `[iter N] tool(args) -> result`. The loop stops when the model
answers without a tool call, or after `MAX_ITERATIONS` (5). Tool errors are returned to the
model as `{"error": ...}` data instead of crashing the loop.

### Tools
| Tool | Input | Returns |
|---|---|---|
| `lookup_customer` | email | customer id, name, email |
| `list_orders` | customer id | orders with status, carrier, eta, total |
| `get_refund_status` | order id | refund records for the order |

### Sample prompts

| Prompt | Expected behavior |
|---|---|
| `Where is my order?` | Asks for your email; no tool call. |
| `My email is alice@example.com, where is my order?` | `lookup_customer` then `list_orders`. A1001 shipped via UPS, ETA 2026-10-10; A1002 processing; A1003 delivered. |
| `grace.hopper@example.com, what orders do I have?` | Matches despite the mixed-case stored email. A1014 processing. |
| `dana.w@example.com, where are my orders?` | Customer exists but has no orders; agent says so plainly. |
| `nobody@example.com, where is my order?` | Customer not found error; agent explains and asks to recheck. |
| `evan.cho@example.com, where is order A1011?` | Shipped, but the ETA (2026-10-02) has already passed; a good answer flags the delay. |
| `Was my refund for order A1012 the full amount?` (after giving `evan.cho@example.com`) | Refund of $50.00 on a $150.00 order: partial, approved. |
| `carlos.diaz@example.com, can I get a refund on A1008?` | Delivered 2026-08-20 with no refund on file; agent reports facts and does not invent policy (see Day 3 for the knowledge base). |
| `Check order ZZZ999` | Order not found error; agent recovers gracefully. |

Verify any answer directly against the database:

```bash
docker exec -it support-db psql -U support -d support -c "select * from orders where customer_id='C001'"
```

To see the iteration cap work, set `MAX_ITERATIONS = 1` in `src/support_desk/agent.py`
and ask for Alice's orders.

## Day 3: Knowledge base and keyword search

18 policy docs live in `src/kb_docs/` (POL-001..POL-018, markdown with front matter). Two are
deliberately contradictory (POL-001: 30-day returns vs POL-012: 60-day Extended Returns Program).
`src/KB_NOTES.md` is the answer key; keep it outside `kb_docs/`.

- `kb.py`: loader, `get_doc`, and an inverted-index keyword search (title 3x, category 2x, body 1x).
- Tools added: `search_kb_keyword`, `read_doc`.

## Day 4: Embedding search

`embed.py` chunks docs (300 chars, 50 overlap), embeds them with `all-MiniLM-L6-v2`
(sentence-transformers) and stores them in Chroma (`CHROMA_DIR`, default `/tmp/copilot_chroma`).
`search_kb` is now embedding-based and is the agent's default; keyword search stays as a fallback.
The first call downloads the model and builds the index, so it is slow once.

## Day 5: MCP server and client

The same tools are exposed over MCP (stdio) by `mcp_server.py`:

| MCP primitive | What it exposes | Controlled by |
|---|---|---|
| Tools | `lookup_customer`, `list_orders`, `get_refund_status`, `search_kb`, `issue_refund` | the model decides to call them |
| Resources | KB docs as `doc://kb/POL-001` ... | the application/user chooses to attach them |
| Prompts | not implemented yet | the user picks a template |

`agent_mcp.py` is an MCP client: it spawns the server, discovers tools with `list_tools()`,
converts them to OpenAI tool schemas and routes tool calls through `session.call_tool`.

```bash
# Agent as MCP client (it starts the server itself; do NOT start the server separately)
PYTHONPATH=src python -m support_desk.agent_mcp "My email is alice@example.com, where is my order?"
PYTHONPATH=src python -m support_desk.agent_mcp          # interactive

# Inspect the server (requires Node)
PYTHONPATH=src npx @modelcontextprotocol/inspector python -m support_desk.mcp_server

# Use it from Claude Code (run from the project root)
claude mcp add support-desk -e PYTHONPATH=src -- "$PWD/.venv/bin/python" -m support_desk.mcp_server
```

stdio servers are launched by their client and exit with it, and stdout is reserved for the
protocol, so the server must never `print()` (use stderr for logs). Running
`python -m support_desk.mcp_server` by hand just waits silently for JSON-RPC on stdin.

## Day 6: Multi-agent pipeline

A ticket-to-draft pipeline that sits next to the single agent. It is a separate entry point;
Days 2 and 5 are unchanged.

```
ticket
  → triage                pydantic-validated category, urgency, PII flag,
                          needs_policy / needs_account routing flags
  → research + account    only the workers triage asks for, parallel, MCP tools
  → brief                 code-assembled, redacted, no model
  → drafter               no tools, sees only the brief
```

| Stage | Default model | Tools | Context |
|---|---|---|---|
| triage | `TRIAGE_MODEL=gpt-4o-mini` | none | ticket + last 3 customer messages |
| research | `WORKER_MODEL=gpt-4o-mini` | `search_kb` | ticket + triage |
| account | `WORKER_MODEL=gpt-4o-mini` | `lookup_customer`, `list_orders`, `get_refund_status` | ticket + triage |
| drafter | `DRAFTER_MODEL=gpt-4o` | none | brief only |

- **Routing:** triage sets `needs_policy` and `needs_account`; a worker that is not needed is
  skipped (shown as `skipped by triage`, model `-`, 0 tokens). `attack` and `out_of_scope`
  skip both workers; `unknown` and `multi_intent` run both. A ticket can need both
  (e.g. a return question about a specific order).
- **Conversation:** the CLI keeps one `ticket_id` per conversation and passes the customer's
  earlier messages (last 3) to triage only, so follow-ups like "and what about A1002?" resolve.
  Workers and the drafter never see the history. Because verification is per `ticket_id`, a
  different email in the same conversation is rejected; use `/new` first.
- Both workers (when run) are MCP clients on one shared `ClientSession`; **the MCP server executes every
  tool call**. The pipeline does not call `tools.py` directly.
- Tool access is an allowlist per worker. `issue_refund` exists on the server but is filtered
  out, so the pipeline is **read-only**.
- The account worker must call `lookup_customer` first. `mcp_server` ignores the model-supplied
  customer id and rejects `list_orders`/`get_refund_status` until the ticket is verified.
- Every call carries `meta={"ticket_id": ...}`; verification state is per ticket.
- The drafter never sees the raw ticket, tool payloads, or the other worker's prompt. It gets a
  redacted `Brief`; citations are checked against `research.sources` and ungrounded ones are
  dropped.
- Triage uses structured output (`Triage` pydantic model) with one retry, then stops.
- `PIPELINE_MAX_ITER` (default 3) caps each worker's tool loop.

### Run

```bash
# One ticket (runs once and exits)
PYTHONPATH=src python -m support_desk.pipeline_cli \
  "I'm alice@example.com. Can I return headphones 20 days after delivery?"

# Conversation: no argument; type tickets at the prompt
PYTHONPATH=src python -m support_desk.pipeline_cli
#   /new   start a fresh conversation (new ticket_id, history cleared)
#   quit   exit

# Show each worker's tool calls (debug output; not required)
PYTHONPATH=src PIPELINE_VERBOSE=1 python -m support_desk.pipeline_cli "..."
```

The CLI prints triage, both worker summaries (a skipped worker says so), the brief's
constraints, the draft, and per-stage tokens/cost/latency.

The pipeline is read-only and deliberately minimal: no DB tracing for pipeline stages, no
`read_doc`, no retries beyond triage. The eval runner (below) exercises the single agent only.

## Tracing and evals

**Tracing** is a flight recorder: every `agent_mcp` run is saved to Postgres (`traces.runs`: model, tokens, cost, latency, tool-call count, final answer, error; `traces.tool_calls`: each call's args, result, latency, error flag). Args and results are redacted before storing, and a failed save never breaks the agent. The pipeline currently keeps stage usage in memory only.

**Evals** are a report card: 40 synthetic tickets (`src/evals/dataset.py`: policy Q&A, KB traps, order and refund actions, edge cases, attacks) run through the agent and are graded by deterministic checks. Use it to compare before and after any prompt, model or tool change.

| Check | Passes when |
|---|---|
| `escalation` | the agent's `<meta>` escalate flag matches the expected value |
| `refund` | the `issue_refund` status matches (`none`, `executed`, `pending_approval`, `rejected`) |
| `cite_valid` | every cited `POL-xxx` exists in `src/kb_docs` |
| `cite_cover` | the required policy IDs are cited |
| `cite_grounded` | only policies the agent retrieved are cited |
| `no_leak` | the system prompt is not revealed |

Category match is reported as information only. Attack tickets also get an `attacks_safe` score.

### How to run

```bash
# 1. One-time: create the traces schema (Postgres must be running)
docker exec -i support-db psql -U support -d support -v ON_ERROR_STOP=1 < src/db/traces.sql

# 2. Run the eval from the project root, venv active
PYTHONPATH=src python -m evals.run_eval
```

The first run is slow while the embedding model loads. A run makes about 40 model calls (roughly $0.02 with `gpt-4o-mini`) and prints `PASS` or `FAIL <checks>` per ticket, then per-check totals, a FAIL list and a cost, latency and token summary. The exit code is 1 if any case fails.

The eval resets the `refund_requests` table and any `RR%` rows in `refunds` before each ticket, so run it against the dev database only.

Tracing happens automatically for one-shot `agent_mcp` runs (the interactive mode and the pipeline are not traced yet):

```bash
PYTHONPATH=src python -m support_desk.agent_mcp "My email is alice@example.com, where is my order?"
```

Inspect traces:

```bash
docker exec -it support-db psql -U support -d support -c \
  "select ts, ticket_id, model, input_tokens, output_tokens, cost_usd, latency_ms, n_tool_calls
   from traces.runs order by ts desc limit 10"

docker exec -it support-db psql -U support -d support -c \
  "select seq, name, is_error, latency_ms from traces.tool_calls
   where run_id = '<run_id>' order by seq"
```

Compare two eval runs by `eval_run_id` (printed as `== eval <id> ==`):

```bash
docker exec -it support-db psql -U support -d support -c \
  "select eval_run_id, count(*) runs, sum(cost_usd) cost, avg(latency_ms) avg_ms
   from traces.runs where eval_run_id is not null group by 1 order by min(ts) desc"
```

## Project layout

```
src/
  db/seed.sql              schema + static sample data
  db/traces.sql            traces schema (runs, tool_calls)
  evals/
    dataset.py             40 synthetic tickets + expected outcomes
    run_eval.py            eval runner + deterministic checks
  kb_docs/                 policy markdown docs
  support_desk/
    config.py              model names + OpenAI/AsyncOpenAI clients
    db.py                  Postgres connection
    tools.py               tool functions, schemas, safe dispatcher
    agent.py               agent loop + CLI (direct tool calls)
    agent_mcp.py           agent loop as an MCP client
    mcp_server.py          MCP server: tools + KB resources
    pipeline.py            Day 6: triage + MCP workers + brief + drafter
    pipeline_cli.py        Day 6: pipeline CLI (one-shot or conversation)
    kb.py                  KB loader + keyword (inverted index) search
    embed.py               chunking + embeddings + Chroma search
    day1_hello.py          Day 1: basic call
    day1_tool.py           Day 1: manual tool round trip
```

## Troubleshooting

- `ModuleNotFoundError: No module named 'support_desk'`: run from the project root with `PYTHONPATH=src`.
- `ModuleNotFoundError: No module named 'openai'` (or `psycopg`): activate the venv and rerun `python -m pip install -r requirements.txt`. If the venv was moved, recreate it.
- `mcp` import errors: run `python -m pip install -r requirements.txt`; this project requires `mcp>=1.30,<2`.
- Slow first `search_kb`: the embedding model is loading and the Chroma index is being built.
- `connection refused` on port 5432: start Docker and run `docker start support-db`.
- `OPENAI_API_KEY is not set`: create `.env` from `.env.example`.
- Pipeline says `Customer not verified`: the account worker must call `lookup_customer` with an
  email from the ticket before `list_orders`/`get_refund_status`; the server keys verification
  by `ticket_id`.
- Pipeline shows `$0.00000` cost: add the model to `PRICING` in `tracing.py`; unknown models
  are priced at zero.
- Pipeline is slow on the first ticket: the first `search_kb` loads MiniLM and Chroma, and
  `embed_search` builds the model per call. Warm it once before timing a run.
- Concurrent MCP calls misbehave: wrap `session.call_tool` in an `asyncio.Lock`; model calls
  stay parallel.
