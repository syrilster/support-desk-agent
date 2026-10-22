CREATE SCHEMA IF NOT EXISTS traces;

CREATE TABLE IF NOT EXISTS traces.runs (
  run_id         UUID PRIMARY KEY,
  ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
  ticket_id      TEXT,
  eval_run_id    TEXT,
  model          TEXT,
  input_tokens   INT,
  output_tokens  INT,
  cost_usd       NUMERIC(12,6),
  latency_ms     DOUBLE PRECISION,
  n_tool_calls   INT,
  n_iterations   INT,
  final_answer   TEXT,
  error          TEXT
);

CREATE TABLE IF NOT EXISTS traces.tool_calls (
  id          BIGSERIAL PRIMARY KEY,
  run_id      UUID NOT NULL REFERENCES traces.runs(run_id) ON DELETE CASCADE,
  seq         INT,
  name        TEXT,
  args        JSONB,
  result      JSONB,
  latency_ms  DOUBLE PRECISION,
  is_error    BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_tc_run    ON traces.tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_eval ON traces.runs(eval_run_id);