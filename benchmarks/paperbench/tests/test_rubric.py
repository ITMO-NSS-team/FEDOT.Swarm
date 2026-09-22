"""The rubric branch: what is refused, what a reading-only judge keeps, and how verdicts
roll up by weight."""

from typing import Any

import pytest
from rubric import (
    JudgeReport,
    Verdict,
    code_development_only,
    leaves_of,
    load_branch,
    rubric_markdown,
    score,
)

TREE: dict[str, Any] = {
    "id": "root",
    "requirements": "The method is reproduced.",
    "weight": 1,
    "sub_tasks": [
        {
            "id": "a",
            "requirements": "The model is defined.",
            "weight": 2,
            "sub_tasks": [],
            "task_category": "Code Development",
        },
        {
            "id": "b",
            "requirements": "Training ran to completion.",
            "weight": 1,
            "sub_tasks": [],
            "task_category": "Code Execution",
        },
        {
            "id": "c",
            "requirements": "The loss matches equation 3.",
            "weight": 1,
            "sub_tasks": [],
            "task_category": "Code Development",
        },
    ],
}


def test_load_branch_returns_the_requirement_and_every_leaf():
    branch, leaves = load_branch(TREE)
    assert branch == "The method is reproduced."
    assert [leaf["id"] for leaf in leaves] == ["a", "b", "c"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "must be a JSON object"),
        ({"requirements": " "}, "non-empty 'requirements'"),
        ({"requirements": "x", "sub_tasks": [{"id": 1, "requirements": "y"}]}, "'id'"),
        (
            {"requirements": "x", "sub_tasks": [{"id": "a", "requirements": "y"}]},
            "non-negative 'weight'",
        ),
        (
            {
                "requirements": "x",
                "sub_tasks": [{"id": "a", "requirements": "y", "weight": True}],
            },
            "non-negative 'weight'",
        ),
    ],
)
def test_load_branch_names_what_is_wrong(data, message):
    with pytest.raises((TypeError, ValueError), match=message):
        load_branch(data)


def test_code_development_only_drops_execution_leaves_and_empty_branches():
    kept = code_development_only(TREE)
    assert kept is not None
    assert [leaf["id"] for leaf in leaves_of(kept)] == ["a", "c"]
    only_execution = {**TREE, "sub_tasks": [TREE["sub_tasks"][1]]}
    assert code_development_only(only_execution) is None


def test_a_leaf_without_a_category_is_kept():
    branch = {"id": "r", "requirements": "x", "weight": 1, "sub_tasks": []}
    assert code_development_only(branch) == branch


def test_rubric_markdown_lists_every_leaf_with_its_weight():
    _, leaves = load_branch(TREE)
    text = rubric_markdown("The method is reproduced.", leaves)
    assert "Branch requirement: The method is reproduced." in text
    assert "- [2] The model is defined." in text
    assert text.count("\n- [") == 3


def test_score_weights_passed_leaves_and_marks_missing_verdicts():
    _, leaves = load_branch(TREE)
    report = JudgeReport(
        verdicts=[
            Verdict(id="a", passed=True, reason="class Model exists"),
            Verdict(id="b", passed=True, reason="ran"),
        ]
    )
    graded = score(leaves, report)
    assert graded["score"] == pytest.approx(3 / 4)
    by_id = {leaf["id"]: leaf for leaf in graded["leaves"]}
    assert by_id["a"]["passed"] and by_id["a"]["reason"] == "class Model exists"
    assert not by_id["c"]["passed"] and by_id["c"]["reason"] == "not graded"
