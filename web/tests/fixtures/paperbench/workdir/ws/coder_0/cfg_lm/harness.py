"""Minimal reproduction of the Language Model Evaluation Harness (Gao et al., 2021).

Implements the two evaluation regimes the paper relies on:

1. Multiple-choice likelihood scoring (ARC-c/e, BoolQ, HellaSwag, PiQA, SciQ,
   WinoGrande): score each candidate continuation with the LM (optionally with
   CFG via ``CFGHFLM``) and take argmax.
2. LAMBADA-style last-token accuracy and TriviaQA substring-match accuracy
   (per Appendix C.1: substring match rather than exact match, following the
   LLaMA methodology modified after manual analysis).

This is API-compatible in spirit with lm-eval; for full runs the paper uses
EleutherAI's harness directly through ``cfg_lm.guidance_wrapper.CFGHFLM``
registered as ``--model cfg-hf``.
"""

from __future__ import annotations

import re
import string
from typing import Dict, List

import torch


# ---------------------------------------------------------------------------
# Task definitions (zero-shot prompts, harness style)
# ---------------------------------------------------------------------------

def _letter(i: int) -> str:
    return string.ascii_uppercase[i]


class MultipleChoiceTask:
    name = "multiple_choice"
    metric = "acc"

    def construct_requests(self, examples: List[Dict]) -> List[Dict]:
        raise NotImplementedError

    def aggregate(self, requests: List[Dict], scores: List[float]) -> Dict[str, float]:
        # group per example by 'task_id'
        by_id: Dict[int, List] = {}
        for req, s in zip(requests, scores):
            by_id.setdefault(req["task_id"], []).append(s)
        correct = 0
        for tid, ss in by_id.items():
            gold = self.gold_index(tid, list(by_id.values()))
            if max(range(len(ss)), key=lambda i: ss[i]) == gold:
                correct += 1
        return {"acc": correct / max(1, len(by_id))}

    def gold_index(self, tid, _):  # override where needed
        return getattr(self, "_golds", {})[tid]


class ArcTask(MultipleChoiceTask):
    """ARC Challenge / Easy zero-shot: stem + choice text, likelihood of label."""

    def __init__(self, challenge=True):
        self.name = "arc_challenge" if challenge else "arc_easy"
        self._golds = {}

    def format_example(self, ex: Dict, idx: int) -> List[tuple]:
        q = f"Question: {ex['question']}\nAnswer:"
        pairs = []
        for lab, txt in zip(ex["labels"], ex["choices"]):
            pairs.append((q + " " + txt, lab))
        self._golds[idx] = ex["answerKey"]
        return pairs

    def build(self, examples: List[Dict]):
        requests, self._golds = [], {}
        for i, ex in enumerate(examples):
            best = None
            for j, (text, lab) in enumerate(self.format_example(ex, i)):
                requests.append({"task_id": i, "context": "", "continuation": text})
                if lab == ex["answerKey"]:
                    best = j
            ex["_gold_pos"] = best
        # gold index = position of answerKey choice
        self._gold_by_id = {}
        pos = 0
        for i, ex in enumerate(examples):
            n = len(ex["choices"])
            self._gold_by_id[i] = ex["labels"].index(ex["answerKey"])
            pos += n
        return requests

    def aggregate(self, requests, scores):
        by_id = {}
        for req, s in zip(requests, scores):
            by_id.setdefault(req["task_id"], []).append(s)
        c = sum(
            1 for tid, ss in by_id.items()
            if max(range(len(ss)), key=lambda i: ss[i]) == self._gold_by_id[tid]
        )
        return {"acc": c / max(1, len(by_id))}


class BoolQTask(MultipleChoiceTask):
    def build(self, examples):
        requests = []
        self._gold_by_id = {}
        for i, ex in enumerate(examples):
            ctx = f"{ex['passage']}\nQuestion: {ex['question']}?\nAnswer:"
            requests.append({"task_id": i, "context": ctx, "continuation": " True"})
            requests.append({"task_id": i, "context": ctx, "continuation": " False"})
            self._gold_by_id[i] = 0 if ex["answer"] else 1
        return requests

    aggregate = ArcTask.aggregate


class HellaSwagTask(MultipleChoiceTask):
    def build(self, examples):
        requests = []
        self._gold_by_id = {}
        for i, ex in enumerate(examples):
            for j, end in enumerate(ex["endings"]):
                requests.append({"task_id": i, "context": ex["ctx"], "continuation": " " + end})
            self._gold_by_id[i] = ex["label"]
        return requests

    aggregate = ArcTask.aggregate


class PiQATask(MultipleChoiceTask):
    def build(self, examples):
        requests = []
        self._gold_by_id = {}
        for i, ex in enumerate(examples):
            ctx = f"Question: {ex['goal']}\nAnswer:"
            for sol in ("sol1", "sol2"):
                requests.append({"task_id": i, "context": ctx, "continuation": " " + ex[sol]})
            self._gold_by_id[i] = max(int(ex["label"]), 0)
        return requests

    aggregate = ArcTask.aggregate


class SciQTask(MultipleChoiceTask):
    def build(self, examples):
        requests = []
        self._gold_by_id = {}
        for i, ex in enumerate(examples):
            opts = [
                ex["distractor1"], ex["distractor2"], ex["distractor3"], ex["correct_answer"]
            ]
            ctx = f"Question: {ex['question']}\nAnswer:"
            for o in opts:
                requests.append({"task_id": i, "context": ctx, "continuation": " " + o})
            self._gold_by_id[i] = 3
        return requests

    aggregate = ArcTask.aggregate


class WinoGrandeTask(MultipleChoiceTask):
    def build(self, examples):
        requests = []
        self._gold_by_id = {}
        for i, ex in enumerate(examples):
            sent = ex["sentence"]
            for opt in (ex["option1"], ex["option2"]):
                requests.append({"task_id": i, "context": sent.replace("_", opt), "continuation": ""})
            try:
                self._gold_by_id[i] = int(ex["answer"]) - 1
            except (TypeError, ValueError):
                self._gold_by_id[i] = 0
        return requests

    aggregate = ArcTask.aggregate


class LambadaTask:
    """LAMBADA (OpenAI): accuracy of predicting the final token."""

    name = "lambada_openai"
    metric = "acc"

    def build(self, examples):
        self.examples = examples
        return [{"task_id": i, "context": ex["text"], "continuation": ""} for i, ex in enumerate(examples)]

    def aggregate_from_last_token_logprobs(self, examples, top1s):
        c = sum(1 for ex, t in zip(examples, top1s) if t == ex["label"])
        return {"acc": c / max(1, len(examples))}


class TriviaQATask:
    """TriviaQA with SUBSTRING matching (Appendix C.1)."""

    name = "triviaqa"
    metric = "acc"

    @staticmethod
    def normalize(s: str) -> str:
        s = s.lower()
        s = "".join(ch for ch in s if ch not in set(string.punctuation))
        s = re.sub(r"\b(a|an|the)\b", " ", s)
        return " ".join(s.split())

    @staticmethod
    def match(prediction: str, golds: List[str]) -> bool:
        pred = TriviaQATask.normalize(prediction)
        return any(TriviaQATask.normalize(g) in pred or pred in TriviaQATask.normalize(g)
                   for g in golds if g)


TASKS = {
    "arc_challenge": ArcTask,
    "arc_easy": ArcTask,
    "boolq": BoolQTask,
    "hellaswag": HellaSwagTask,
    "piqa": PiQATask,
    "sciq": SciQTask,
    "winogrande": WinoGrandeTask,
    "lambada_openai": LambadaTask,
    "triviaqa": TriviaQATask,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_multiple_choice(lm, task, examples: List[Dict], use_cfg: bool = True) -> Dict[str, float]:
    """Evaluate a multiple-choice task against a CFGHFLM-like object."""
    requests = task.build(examples)
    scores = []
    for req in requests:
        if use_cfg and hasattr(lm, "score_sequence"):
            ctx = lm.tok_encode(req["context"])
            cont = lm.tokenizer(req["continuation"], add_special_tokens=False).input_ids
            scores.append(lm.score_sequence(ctx, cont) if cont else 0.0)
        else:
            lp = lm._last_logprobs_no_cfg(lm.tok_encode(req["context"] + req["continuation"]))
            cont_ids = lm.tokenizer(req["continuation"], add_special_tokens=False).input_ids
            scores.append(float(sum(lp[-len(cont_ids):][i, t] for i, t in enumerate(reversed(cont_ids)))) if cont_ids else 0.0)
    return task.aggregate(requests, scores)
