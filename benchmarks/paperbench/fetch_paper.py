"""Fetches a paper's PaperBench package into `data/<paper>/`: the rubric, the PDF, the
authors' markdown, the addendum and the blacklist, straight from the openai/frontier-evals
repository. The rubric is filtered to its Code Development leaves, the only ones a judge
that reads code and never runs it can grade; the upstream markdown is kept beside the
run's own conversion as `paper.upstream.md` for comparison.

uv run python benchmarks/paperbench/fetch_paper.py --paper stochastic-interpolants
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from rubric import code_development_only, leaves_of

DATA = Path(__file__).parent / "data"
BASE = "https://raw.githubusercontent.com/openai/frontier-evals/main/project/paperbench/data/papers"
# the PDF and the markdown are stored with Git LFS, so the raw URL answers with a pointer
# and the bytes come from the media host
MEDIA = "https://media.githubusercontent.com/media/openai/frontier-evals/main/project/paperbench/data/papers"
FILES = ("rubric.json", "paper.pdf", "paper.md", "addendum.md", "blacklist.txt")
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"


def fetch(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def main(paper: str) -> None:
    target = DATA / paper
    target.mkdir(parents=True, exist_ok=True)
    got: dict[str, int] = {}
    for name in FILES:
        body = fetch(f"{BASE}/{paper}/{name}")
        if body is None:
            print(f"{name}: not in the upstream package", file=sys.stderr)
            continue
        if body.startswith(LFS_POINTER):
            body = fetch(f"{MEDIA}/{paper}/{name}") or body
        dest = target / ("paper.upstream.md" if name == "paper.md" else name)
        dest.write_bytes(body)
        got[dest.name] = len(body)
    rubric = json.loads((target / "rubric.json").read_text())
    branch = code_development_only(rubric)
    if branch is None:
        raise SystemExit("the rubric has no Code Development leaves")
    (target / "rubric_branch.json").write_text(json.dumps(branch, indent=2))
    total, kept = len(leaves_of(rubric)), len(leaves_of(branch))
    (target / "README.md").write_text(
        f"# {paper} (Code Development only)\n\n"
        f"Fetched by `fetch_paper.py` from the PaperBench package in openai/frontier-evals. "
        f"`rubric_branch.json` keeps the {kept} Code Development leaves of the {total}-leaf "
        f"rubric, the ones a judge that reads code and never runs it can grade; "
        f"`rubric.json` is the whole tree. `paper.upstream.md` is the authors' own "
        f"markdown, kept for comparison with what `parse_pdf.py` makes of `paper.pdf`.\n\n"
        f"```bash\nuv run --extra pydantic-ai --extra opencode --group paperbench "
        f"python benchmarks/paperbench/run.py --paper {paper} "
        f"--paper-pdf benchmarks/paperbench/data/{paper}/paper.pdf --usd 1.2\n```\n"
    )
    print(json.dumps({"paper": paper, "files": got, "leaves": kept, "of": total}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--paper", default="stochastic-interpolants")
    main(p.parse_args().paper)
