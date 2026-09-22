"""One branch of a PaperBench rubric: how it is loaded, filtered to what a reading-only judge
can grade, rendered for the workers, and scored from the judge's verdicts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

CODE_DEVELOPMENT = "Code Development"


def leaves_of(node: dict[str, Any]) -> list[dict[str, Any]]:
    if not node.get("sub_tasks"):
        return [node]
    out: list[dict[str, Any]] = []
    for sub in node["sub_tasks"]:
        out.extend(leaves_of(sub))
    return out


def load_branch(data: Any) -> tuple[str, list[dict[str, Any]]]:
    """Branch requirements plus leaves, or an error naming what is wrong with them."""
    if not isinstance(data, dict):
        raise TypeError("rubric branch must be a JSON object")
    requirements = data.get("requirements")
    if not isinstance(requirements, str) or not requirements.strip():
        raise ValueError("rubric branch needs a non-empty 'requirements' string")
    leaves = leaves_of(data)
    if not leaves:
        raise ValueError("rubric branch has no leaves to grade")
    for leaf in leaves:
        if not isinstance(leaf.get("id"), str) or not leaf["id"].strip():
            raise ValueError("every rubric leaf needs a non-empty string 'id'")
        if (
            not isinstance(leaf.get("requirements"), str)
            or not leaf["requirements"].strip()
        ):
            raise ValueError(
                f"rubric leaf {leaf.get('id')!r} needs non-empty 'requirements'"
            )
        weight = leaf.get("weight")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or weight < 0
        ):
            raise ValueError(
                f"rubric leaf {leaf['id']!r} needs a non-negative 'weight'"
            )
    return requirements, leaves


def code_development_only(node: dict[str, Any]) -> dict[str, Any] | None:
    """The same tree with only its Code Development leaves, the ones a judge that reads
    code and never runs it can grade. A branch left without leaves is dropped, and a leaf
    without a category is kept, since a hand-written rubric carries none."""
    if not node.get("sub_tasks"):
        category = node.get("task_category")
        return node if category in (None, CODE_DEVELOPMENT) else None
    kept = [
        sub
        for sub in (code_development_only(s) for s in node["sub_tasks"])
        if sub is not None
    ]
    if not kept:
        return None
    return {**node, "sub_tasks": kept}


def rubric_markdown(branch: str, leaves: list[dict[str, Any]]) -> str:
    """The branch as a checklist the workers read from their workspace."""
    lines = [
        "# Rubric",
        "",
        f"Branch requirement: {branch}",
        "",
        (
            f"{len(leaves)} leaves, graded by reading the code, never by running it. "
            "Weight in brackets."
        ),
        "",
    ]
    lines += [f"- [{leaf['weight']}] {leaf['requirements']}" for leaf in leaves]
    return "\n".join(lines) + "\n"


class Verdict(BaseModel):
    id: str
    passed: bool
    reason: str


class JudgeReport(BaseModel):
    verdicts: list[Verdict]


def judge_prompt(leaves: list[dict[str, Any]], code: str) -> str:
    checks = "\n".join(f"- [{leaf['id']}] {leaf['requirements']}" for leaf in leaves)
    return (
        "You are reviewing a code repository against a grading rubric, by reading it, "
        "not running it. The repository is already given in full below, one file per "
        "section, so there is nothing to read or run: do not inspect the working "
        "directory or execute anything, just answer from what is here.\n\n"
        f"Repository:\n{code}\n\n"
        f"For each requirement, say whether the code satisfies it and why:\n{checks}\n\n"
        "Answer with only a JSON object, no other text: "
        '{"verdicts": [{"id": "...", "passed": true or false, "reason": "..."}, ...]}, '
        "one entry per requirement above, in the same order."
    )


def batches(leaves: list[dict[str, Any]], size: int = 20) -> list[list[dict[str, Any]]]:
    """The rubric in slices a judge can answer in one structured reply."""
    return [leaves[i : i + size] for i in range(0, len(leaves), size)]


def score(leaves: list[dict[str, Any]], report: JudgeReport) -> dict[str, Any]:
    """Weighted share of leaves passed, plus every leaf with its verdict and reason."""
    verdict_by_id = {v.id: v for v in report.verdicts}
    total = sum(leaf["weight"] for leaf in leaves)
    passed = sum(
        leaf["weight"]
        for leaf in leaves
        if (v := verdict_by_id.get(leaf["id"])) and v.passed
    )
    graded = []
    for leaf in leaves:
        v = verdict_by_id.get(leaf["id"])
        graded.append(
            {
                "id": leaf["id"],
                "requirements": leaf["requirements"],
                "weight": leaf["weight"],
                "passed": bool(v.passed) if v else False,
                "reason": v.reason if v else "not graded",
            }
        )
    return {"score": passed / total if total else 0.0, "leaves": graded}
