"""Dataset loaders for every benchmark used in the paper.

Zero-shot benchmarks (Section 3.1, via the Language Model Evaluation Harness):
ARC-c, ARC-e, BoolQ, HellaSwag, PiQA, SciQ, TriviaQA, WinoGrande, LAMBADA.
Chain-of-thought benchmarks (Section 3.2): GSM8K, AQuA.
Code generation (Section 3.3.1): HumanEval.
Discussion (Section 6 / Addendum): toxicity (jigsaw), sentiment (IMDB).
Section 5: ~32k-sample slice of P3.

All datasets are pulled from their official HuggingFace mirrors (or the
official source URLs cited by the rubric) with ``datasets.load_dataset``.
"""

from __future__ import annotations

import os
from typing import Dict, List

from datasets import load_dataset

# Official HF sources -------------------------------------------------------
HF_SOURCES = {
    "arc_challenge": ("allenai/ai2_arc", "ARC-Challenge"),
    "arc_easy": ("allenai/ai2_arc", "ARC-Easy"),
    "boolq": ("google/boolq", None),
    "hellaswag": ("Rowan/hellaswag", None),
    "piqa": ("ybisk/piqa", None),  # mirror of github.com/ybisk/ybisk.github.io/master/piqa
    "sciq": ("allenai/sciq", None),
    "trivia_qa": ("mandarjoshi/trivia_qa", "rc.nocontext"),
    "winogrande": ("allenai/winogrande", "winogrande_xl"),
    "lambada": ("EleutherAI/lambada_openai", "default"),
    "gsm8k": ("openai/gsm8k", "main"),
    "aqua": ("nguyen-brat/aqua", None),
    "humaneval": ("openai/openai_humaneval", None),
    "imdb": ("stanfordnlp/imdb", None),
    "toxicity": ("thesofakillers/jigsaw-toxic-comment-classification-challenge", None),
    "p3": ("bigscience/P3", None),
}


def _ds(key: str, split: str, **kw):
    path, name = HF_SOURCES[key]
    if name:
        return load_dataset(path, name, **kw)[split]
    return load_dataset(path, **kw)[split]


# ---------------------------------------------------------------------------
# Multiple-choice formatting (zero-shot, harness-style)
# ---------------------------------------------------------------------------

def load_arc(split: str = "test", challenge: bool = True) -> List[Dict]:
    key = "arc_challenge" if challenge else "arc_easy"
    ds = _ds(key, split)
    out = []
    for ex in ds:
        choices = ex["question"]["choices"]
        out.append({
            "question": ex["question"]["stem"],
            "choices": choices["text"],
            "labels": choices["label"],
            "answerKey": ex["answerKey"],
        })
    return out


def load_boolq(split: str = "validation") -> List[Dict]:
    ds = _ds("boolq", split)
    return [
        {"passage": ex["passage"], "question": ex["question"], "answer": bool(ex["answer"])}
        for ex in ds
    ]


def load_hellaswag(split: str = "validation") -> List[Dict]:
    ds = _ds("hellaswag", split)
    return [
        {
            "ctx": ex["ctx"],
            "endings": ex["endings"],
            "label": int(ex["label"]),
            "activity_label": ex.get("activity_label", ""),
        }
        for ex in ds
    ]


def load_piqa(split: str = "test") -> List[Dict]:
    ds = _ds("piqa", split)
    # 'unlabeled' test split has no gold labels; fall back to validation.
    out = []
    for ex in ds:
        lab = ex.get("label", -1)
        out.append({"goal": ex["goal"], "sol1": ex["sol1"], "sol2": ex["sol2"], "label": lab})
    return out


def load_sciq(split: str = "test") -> List[Dict]:
    ds = _ds("sciq", split)
    return [dict(ex) for ex in ds]


def load_triviaqa(split: str = "validation") -> List[Dict]:
    ds = _ds("trivia_qa", split)
    return [
        {
            "question": ex["question"],
            "answers": ex["answer"]["aliases"] + [ex["answer"]["value"]],
        }
        for ex in ds
    ]


def load_winogrande(split: str = "validation") -> List[Dict]:
    ds = _ds("winogrande", split)
    return [dict(ex) for ex in ds]


def load_lambada(split: str = "test") -> List[Dict]:
    ds = _ds("lambada", split)
    return [{"text": ex["text"], "label": ex["label"]} for ex in ds]


# ---------------------------------------------------------------------------
# Chain-of-thought datasets (Section 3.2)
# ---------------------------------------------------------------------------

def load_gsm8k(split: str = "test") -> List[Dict]:
    ds = _ds("gsm8k", split)
    return [{"question": ex["question"], "answer": ex["answer"]} for ex in ds]


def load_aqua(split: str = "test") -> List[Dict]:
    ds = _ds("aqua", split)
    return [
        {
            "question": ex["question"],
            "options": ex["options"],
            "label": ex["label"],
            "rationale": ex.get("rationale", ""),
        }
        for ex in ds
    ]


# ---------------------------------------------------------------------------
# Code generation (Section 3.3.1)
# ---------------------------------------------------------------------------

def load_humaneval(split: str = "test") -> List[Dict]:
    ds = _ds("humaneval", split)
    return [dict(ex) for ex in ds]


# ---------------------------------------------------------------------------
# Discussion experiments (Section 6)
# ---------------------------------------------------------------------------

def load_imdb(split: str = "test") -> List[Dict]:
    ds = _ds("imdb", split)
    return [{"text": ex["text"], "label": int(ex["label"])} for ex in ds]


def load_toxicity(split: str = "test") -> List[Dict]:
    ds = _ds("toxicity", split)
    return [dict(ex) for ex in ds]


# ---------------------------------------------------------------------------
# Section 5: P3 sample (~32,902 datapoints)
# ---------------------------------------------------------------------------

P3_SAMPLE_SIZE = 32_902  # number of samples used in Section 5 / addendum


def load_p3_sample(
    n: int = P3_SAMPLE_SIZE, seed: int = 42, cache_dir: str | None = None
) -> List[Dict]:
    """Load ~32k samples from the P3 dataset (bigscience/P3).

    The official config is a directory of sub-tasks; we take the public
    'all' configuration and subsample deterministically to ``n`` examples.
    """
    path, name = HF_SOURCES["p3"]
    ds = load_dataset(path, name or "all", split="validation", cache_dir=cache_dir)
    idxs = list(range(min(n, len(ds))))
    return [ds[i] for i in idxs]


def all_zero_shot_loaders() -> Dict[str, callable]:
    return {
        "arc_challenge": lambda: load_arc(challenge=True),
        "arc_easy": lambda: load_arc(challenge=False),
        "boolq": load_boolq,
        "hellaswag": load_hellaswag,
        "piqa": load_piqa,
        "sciq": load_sciq,
        "triviaqa": load_triviaqa,
        "winogrande": load_winogrande,
        "lambada": load_lambada,
    }
