"""The paper as the swarm reads it: a brief for the composer and the feed, the full text for
workers that have no file system, and a digest of the inputs for the record."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

BRIEF_CHARS = 1500
BRIEF_LEAVES = 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def off_limits(blacklist: list[str]) -> str:
    return ", ".join(blacklist) if blacklist else "the paper's own repository"


def paper_topic(
    summary: str, blacklist: list[str], leaves: list[dict[str, Any]]
) -> str:
    """The whole paper plus every rubric leaf, for workers whose only input is the prompt."""
    checks = "\n".join(f"- {leaf['requirements']}" for leaf in leaves)
    return (
        f"{summary}\n\n"
        "Write, in Python, the training step described above, refining it across as many "
        "rounds as it takes. Do not run training, do not download any dataset or "
        f"pretrained weights, and do not access {off_limits(blacklist)}: work only from "
        "the description above.\n\n"
        f"Your final post must satisfy every requirement below:\n{checks}"
    )


def paper_brief(
    summary: str, blacklist: list[str], branch: str, leaves: list[dict[str, Any]]
) -> str:
    """The opening of the paper and a sample of the rubric, for workers that have the full
    `paper.md` and `rubric.md` in their workspace and for the composer writing the cast."""
    head = summary.strip()[:BRIEF_CHARS]
    if len(summary.strip()) > BRIEF_CHARS:
        head = head.rsplit(" ", 1)[0] + " ..."
    sample = "\n".join(f"- {leaf['requirements']}" for leaf in leaves[:BRIEF_LEAVES])
    more = (
        f"\n- ... and {len(leaves) - BRIEF_LEAVES} more in rubric.md"
        if len(leaves) > BRIEF_LEAVES
        else ""
    )
    return (
        f"Reproduce the code of this paper in your workspace. The paper begins:\n\n"
        f"{head}\n\n"
        f"The full text is in paper.md and the grading rubric in rubric.md, both in your "
        f"working directory. The branch under review: {branch}\n\n"
        f"Do not run training, do not download any dataset or pretrained weights, and do "
        f"not access {off_limits(blacklist)}.\n\n"
        f"The rubric's {len(leaves)} leaves, graded by reading your code, start with:\n"
        f"{sample}{more}"
    )
