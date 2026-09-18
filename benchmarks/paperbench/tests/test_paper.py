"""The brief a workspace voice reads is short and points at the files; the topic a prompt
voice reads carries the whole paper."""

from pathlib import Path

from paper import BRIEF_CHARS, paper_brief, paper_topic, sha256_of

LEAVES = [
    {"id": str(i), "requirements": f"Requirement {i}", "weight": 1} for i in range(25)
]


def test_the_brief_cuts_the_paper_and_samples_the_rubric():
    summary = "word " * 2000
    brief = paper_brief(summary, ["github.com/x/y"], "All of it.", LEAVES)
    assert len(brief) < BRIEF_CHARS + 2500
    assert brief.count("- Requirement") == 20
    assert "and 5 more in rubric.md" in brief
    assert "github.com/x/y" in brief
    assert "paper.md" in brief and "rubric.md" in brief


def test_the_topic_carries_the_whole_paper_and_every_leaf():
    summary = "word " * 2000
    topic = paper_topic(summary, [], LEAVES)
    assert summary.strip() in topic
    assert topic.count("- Requirement") == 25
    assert "the paper's own repository" in topic


def test_sha256_of_reads_the_file(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"abc")
    assert sha256_of(path).startswith("ba7816bf")
