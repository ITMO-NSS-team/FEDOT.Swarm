"""Cleans a paper's PDF into plain text for PaperBench runs, as an alternative to
`parse_tex.py` for a paper whose LaTeX source is not at hand — arXiv's own PDF, say.

No OCR: an arXiv PDF is born-digital (a real text layer, not a scan), so pymupdf's plain
text extraction is enough. That also means, unlike `parse_tex.py`, this only ever sees
what the renderer laid out on the page — inline math comes out as unicode glyphs
(`αt = 1 − t`), not the `$...$` source, and a badly-set multi-line equation or a table can
still come out scrambled. Prefer `parse_tex.py` when the LaTeX source is available; this
is the fallback for when it is not.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pymupdf

DATA = Path(__file__).parent / "data"

# A line the renderer repeats near-verbatim on most pages is a running header or footer
# (the paper's own title, a page number, a venue banner) — noise repeated once per page,
# not part of the paper's argument. Short lines are left alone even if they recur: a
# genuine one- or two-character fragment (a lone "0" or "t" from some formula) recurs by
# coincidence far more often than a real header does.
_HEADER_MIN_CHARS = 15
_HEADER_MIN_SHARE = 0.6


def _strip_running_headers(pages: list[str]) -> list[str]:
    counts: Counter[str] = Counter()
    for page in pages:
        for line in {line.strip() for line in page.split("\n") if line.strip()}:
            counts[line] += 1
    threshold = max(2, int(len(pages) * _HEADER_MIN_SHARE))
    noise = {
        line
        for line, n in counts.items()
        if n >= threshold and len(line) >= _HEADER_MIN_CHARS
    }
    if not noise:
        return pages
    return [
        "\n".join(line for line in page.split("\n") if line.strip() not in noise)
        for page in pages
    ]


def convert(source: Path, out_md: Path) -> dict:
    doc = pymupdf.open(source)
    pages = [page.get_text() for page in doc]
    doc.close()
    pages = _strip_running_headers(pages)
    text = "\n\n".join(page.strip() for page in pages if page.strip())
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(text)
    return {"source": str(source), "pages": len(pages), "chars": len(text)}


def cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--paper", default="stochastic-interpolants")
    p.add_argument(
        "--source",
        default=None,
        help="a .pdf file; defaults to data/<paper>/paper.pdf",
    )
    p.add_argument("--out", default=None, help="defaults to data/<paper>/paper.md")
    p.add_argument(
        "--force", action="store_true", help="overwrite an existing paper.md"
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="report whether paper.md exists without converting",
    )
    return p.parse_args()


def resolve_source(paper_dir: Path, source: str | None) -> Path:
    return Path(source) if source else paper_dir / "paper.pdf"


def main(args: argparse.Namespace) -> None:
    paper_dir = DATA / args.paper
    out_md = Path(args.out) if args.out else paper_dir / "paper.md"
    if args.check:
        print(
            json.dumps(
                {
                    "paper": args.paper,
                    "paper_md": str(out_md),
                    "exists": out_md.exists(),
                }
            )
        )
        return
    if out_md.exists() and not args.force:
        print(f"{out_md} already exists, pass --force to reconvert.")
        return
    source = resolve_source(paper_dir, args.source)
    if not source.exists():
        raise SystemExit(f"No PDF at {source}: pass --source <file>.")
    meta = convert(source, out_md)
    print(json.dumps({"paper_md": str(out_md), **meta}, ensure_ascii=False))


if __name__ == "__main__":
    main(cli())
