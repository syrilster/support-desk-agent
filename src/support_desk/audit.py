import json
from datetime import datetime, timezone
from pathlib import Path

from support_desk.redact import redact

LOG = Path("logs/audit.jsonl")


def audit(event: str, **fields) -> None:
    LOG.parent.mkdir(exist_ok=True)
    line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}, default=str)
    with LOG.open("a") as f:
        f.write(redact(line) + "\n")