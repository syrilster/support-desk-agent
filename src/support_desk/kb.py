from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from collections import defaultdict

KB_DIR = Path(os.getenv("KB_DIR", Path(__file__).resolve().parents[1] / "kb_docs"))

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "can", "i", "my", "me", "do", "does", "how", "what", "be", "it", "we", "you"
}


@dataclass(frozen=True)
class Doc:
    id: str
    title: str
    category: str
    last_updated: str
    body: str


def _parse(path: Path) -> Doc:
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(text)
    if not match:
        raise ValueError(f"{path.name}: missing front matter (--- block at top of file)")

    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip("\"'")

    if "id" not in meta:
        raise ValueError(f"{path.name}: front matter has no 'id'")

    return Doc(
        id=meta["id"],
        title=meta.get("title", ""),
        category=meta.get("category", ""),
        last_updated=meta.get("last_updated", ""),
        body=match.group(2).strip(),
    )


@lru_cache(maxsize=1)
def load_kb() -> dict[str, Doc]:
    if not KB_DIR.is_dir():
        raise FileNotFoundError(f"KB folder not found: {KB_DIR}")

    docs: dict[str, Doc] = {}
    for path in sorted(KB_DIR.glob("*.md")):
        doc = _parse(path)
        if doc.id in docs:
            raise ValueError(f"{path.name}: duplicate id {doc.id}")
        docs[doc.id] = doc
    return docs


def get_doc(doc_id: str) -> Doc | None:
    return load_kb().get(doc_id.strip().upper())


# "How long does a bank transfer refund take?"
# ["long", "bank", "transfer", "refund", "take"]
def _tokenize(text: str) -> list[str]:
    """Lowercase, split, remove stopwords."""
    import re
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def _build_index() -> dict[str, dict[str, int]]:
    """Build inverted index: word -> {doc_id: count}"""
    index: dict[str, dict[str, int]] = defaultdict(dict)
    for doc in load_kb().values():
        for word in _tokenize(doc.title) * 3 + _tokenize(doc.body):
            index[word][doc.id] = index[word].get(doc.id, 0) + 1
    return index


"""
unique search terms
     │
     ├── "long"     → find matching docs → add scores
     ├── "bank"     → find matching docs → add scores
     ├── "transfer" → find matching docs → add scores
     ├── "refund"   → find matching docs → add scores
     └── "take"     → find matching docs → add scores
     │
     ▼
scores
{
  "POL-002": 13,
  "POL-005": 3,
  "POL-001": 1
}
     │
     ▼
sort by score
     │
     ▼
[("POL-002", 13), ("POL-005", 3), ...]
"""


def search_kb(query: str, limit: int = 5) -> list[tuple[str, int]]:
    """Return top doc IDs by score. Each word in query searches the index."""
    index = _build_index()
    scores: dict[str, int] = defaultdict(int)

    for word in set(_tokenize(query)):  # set() to count each unique word once
        for doc_id, count in index.get(word, {}).items():
            scores[doc_id] += min(count, 5)  # capping here so long docs don't dominate
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
