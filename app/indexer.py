"""Zerlegt die gecrawlten Seiten in Abschnitte und baut einen BM25-Suchindex."""
from __future__ import annotations

import json
import pickle
import re
from datetime import datetime, timezone

from rank_bm25 import BM25Okapi

from .config import DATA_DIR

CHUNK_SIZE = 1100
CHUNK_OVERLAP = 200

_token_re = re.compile(r"[a-zA-ZäöüÄÖÜß0-9]+")
_UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def tokenize(text: str) -> list[str]:
    return [t.lower().translate(_UMLAUT) for t in _token_re.findall(text)]


def chunk_text(text: str) -> list[str]:
    """Teilt Text an Absatzgrenzen in ~CHUNK_SIZE-Zeichen-Abschnitte mit Überlappung."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if len(cur) + len(p) + 2 <= CHUNK_SIZE or not cur:
            cur = f"{cur}\n\n{p}".strip()
        else:
            chunks.append(cur)
            cur = (cur[-CHUNK_OVERLAP:] + "\n\n" + p) if CHUNK_OVERLAP else p
        # Überlange Einzelabsätze hart teilen
        while len(cur) > CHUNK_SIZE * 1.5:
            chunks.append(cur[:CHUNK_SIZE])
            cur = cur[CHUNK_SIZE - CHUNK_OVERLAP :]
    if cur:
        chunks.append(cur)
    return chunks


def build_index() -> dict:
    pages = json.loads((DATA_DIR / "pages.json").read_text(encoding="utf-8"))
    chunks: list[dict] = []
    for page in pages:
        for part in chunk_text(page.get("text", "")):
            if len(part) < 80:  # Mini-Schnipsel (Menüreste etc.) überspringen
                continue
            chunks.append(
                {
                    "url": page["url"],
                    "title": page.get("title", page["url"]),
                    "source": page.get("source", "website"),
                    "text": part,
                }
            )
    if not chunks:
        raise RuntimeError("Keine Chunks — Index nicht gebaut.")

    bm25 = BM25Okapi([tokenize(c["title"] + "\n" + c["text"]) for c in chunks])
    index = {
        "chunks": chunks,
        "bm25": bm25,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(DATA_DIR / "index.pkl", "wb") as f:
        pickle.dump(index, f)
    print(f"Index gebaut: {len(chunks)} Abschnitte aus {len(pages)} Seiten")
    return {"chunks": len(chunks), "pages": len(pages)}


if __name__ == "__main__":
    build_index()
