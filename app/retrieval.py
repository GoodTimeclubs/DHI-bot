"""Sucht die relevantesten Website-Abschnitte zu einer Nutzerfrage (BM25)."""
from __future__ import annotations

import json
import pickle
import threading

from .config import DATA_DIR
from .indexer import tokenize

_lock = threading.Lock()
_cache: dict = {"mtime": None, "index": None, "termine_mtime": None, "termine": None}


def _load_index():
    path = DATA_DIR / "index.pkl"
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    with _lock:
        if _cache["mtime"] != mtime:
            with open(path, "rb") as f:
                _cache["index"] = pickle.load(f)
            _cache["mtime"] = mtime
        return _cache["index"]


def get_termine() -> dict:
    path = DATA_DIR / "termine.json"
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    with _lock:
        if _cache["termine_mtime"] != mtime:
            _cache["termine"] = json.loads(path.read_text(encoding="utf-8"))
            _cache["termine_mtime"] = mtime
        return _cache["termine"] or {}


# Bei Preis-/Zahlungsfragen die Ablefy-Buchungsseiten hochgewichten —
# dort stehen die konkreten Preise, Raten- und Skonto-Angaben.
_PRICE_HINTS = ("preis", "kost", "teuer", "rate", "zahl", "skonto", "rabatt",
                "euro", "€", "gebühr", "gebuehr", "investition", "finanzier")


def search(query: str, k: int = 6) -> list[dict]:
    index = _load_index()
    if index is None:
        return []
    chunks = index["chunks"]
    scores = list(index["bm25"].get_scores(tokenize(query)))
    q = query.lower()
    price_q = any(h in q for h in _PRICE_HINTS)
    if price_q:
        for i, c in enumerate(chunks):
            if c.get("source") == "buchungsseite":
                scores[i] *= 1.8
    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    out: list[dict] = []
    per_url: dict[str, int] = {}
    for i in ranked:
        if scores[i] <= 0 or len(out) >= k:
            break
        c = chunks[i]
        if per_url.get(c["url"], 0) >= 2:  # max. 2 Abschnitte pro Seite
            continue
        per_url[c["url"]] = per_url.get(c["url"], 0) + 1
        out.append({**c, "score": float(scores[i])})

    # Bei Preisfragen garantieren, dass mindestens zwei Buchungsseiten-Abschnitte
    # (mit den konkreten Preisen) im Kontext landen.
    if price_q:
        have = sum(1 for c in out if c.get("source") == "buchungsseite")
        if have < 2:
            best_b = sorted(
                (i for i, c in enumerate(chunks) if c.get("source") == "buchungsseite"),
                key=lambda i: scores[i],
                reverse=True,
            )
            used = {(c["url"], c["text"][:60]) for c in out}
            for i in best_b:
                if have >= 2:
                    break
                c = chunks[i]
                if (c["url"], c["text"][:60]) in used:
                    continue
                if len(out) >= k:
                    # schwächsten Nicht-Buchungs-Treffer ersetzen
                    for j in range(len(out) - 1, -1, -1):
                        if out[j].get("source") != "buchungsseite":
                            out.pop(j)
                            break
                    else:
                        break
                out.append({**c, "score": float(scores[i])})
                have += 1
    return out


def stats() -> dict:
    index = _load_index()
    termine = get_termine()
    return {
        "index_built_at": index["built_at"] if index else None,
        "chunks": len(index["chunks"]) if index else 0,
        "termine": len(termine.get("seminars", [])),
        "termine_fetched_at": termine.get("fetched_at"),
    }
