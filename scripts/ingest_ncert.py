#!/usr/bin/env python3
"""Download NCERT maths textbooks + standards PDFs and prepare them for KG refinement.

Usage:
  python3 scripts/ingest_ncert.py download            # fetch all PDFs into data/raw/
  python3 scripts/ingest_ncert.py download --class 6  # one class only
  python3 scripts/ingest_ncert.py extract             # PDFs -> data/text/*.txt (needs pypdf)
  python3 scripts/ingest_ncert.py status              # what's downloaded/extracted

Then refine the graph with the tutor agent:
  claude -p "Read data/text/class6_*.txt chapter by chapter. Compare against the g6.* nodes
  in kg/bands/g6-8.json: fix chapter mappings, add missing misconceptions and learning
  outcomes, propose node splits where a chapter covers more than one concept. Follow
  harness/rules/50-self-improvement.md; run scripts/validate_kg.py after edits."

Notes:
- NCERT chapter PDFs: https://ncert.nic.in/textbook/pdf/{code}{chapter:02d}.pdf
  (some older books use 1-digit chapter numbers; we try both).
- Run from a network-unrestricted machine; the hosted authoring environment blocks
  ncert.nic.in. Downloads are polite: sequential with a delay, resumable (skips existing).
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
TEXT = ROOT / "data" / "text"
UA = {"User-Agent": "SubjectKG-ingest/1.0 (educational; contact repo owner)"}


def load_manifest() -> dict:
    return json.loads((ROOT / "kg" / "sources" / "manifest.json").read_text())


def fetch(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 10_000:
        return True
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        # real PDFs start with %PDF; size alone lets HTML error pages through
        if len(data) < 10_000 or not data.startswith(b"%PDF"):
            return False
        dest.write_bytes(data)
        return True
    except Exception as e:
        print(f"  FAIL {url}: {e}")
        if dest.exists():
            dest.unlink()
        return False


def download(only_class: int | None) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    man = load_manifest()
    for book in man["ncert_textbooks"]:
        if only_class and book["class"] != only_class:
            continue
        code = book["code"]
        print(f"Class {book['class']}: {book['title']} ({code})")
        for ch in range(1, book["chapters"] + 1):
            dest = RAW / f"class{book['class']:02d}_{code}_ch{ch:02d}.pdf"
            ok = fetch(f"https://ncert.nic.in/textbook/pdf/{code}{ch:02d}.pdf", dest) or \
                 fetch(f"https://ncert.nic.in/textbook/pdf/{code}{ch}.pdf", dest)
            print(f"  ch{ch:02d}: {'ok' if ok else 'MISSING'}")
            time.sleep(1.5)
    for doc in man["standards_documents"]:
        if not doc["url"].lower().endswith(".pdf"):
            continue
        name = doc["url"].rsplit("/", 1)[-1]
        print(f"Standards doc: {name}")
        fetch(doc["url"], RAW / name)
        time.sleep(1.5)


def extract() -> None:
    try:
        from pypdf import PdfReader  # pip install pypdf
    except ImportError:
        print("pip install pypdf first")
        sys.exit(1)
    TEXT.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(RAW.glob("*.pdf")):
        out = TEXT / (pdf.stem + ".txt")
        if out.exists():
            continue
        try:
            reader = PdfReader(str(pdf))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
            out.write_text(text)
            print(f"extracted {pdf.name} -> {out.name} ({len(text)} chars)")
        except Exception as e:
            print(f"FAIL {pdf.name}: {e}")


def status() -> None:
    pdfs = list(RAW.glob("*.pdf")) if RAW.exists() else []
    txts = list(TEXT.glob("*.txt")) if TEXT.exists() else []
    print(f"{len(pdfs)} PDFs in data/raw/, {len(txts)} extracted texts in data/text/")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["download", "extract", "status"])
    ap.add_argument("--class", dest="only_class", type=int)
    args = ap.parse_args()
    {"download": lambda: download(args.only_class), "extract": extract, "status": status}[args.cmd]()


if __name__ == "__main__":
    main()
