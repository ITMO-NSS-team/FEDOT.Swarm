"""Reproduction of 'Stay on topic with Classifier-Free Guidance' (Sanchez et al., 2023).

Modules
-------
cfg              : Core Classifier-Free Guidance math (Eq. 7) and HF-model wrappers.
guidance_wrapper : lm-evaluation-harness wrapper applying CFG to any HuggingFace LM.
harness          : Minimal self-contained evaluation harness (loglikelihood reimplementation).
data             : Dataset loading for all benchmarks used in the paper.
cot_prompts      : Wang et al. (2023) self-consistency few-shot CoT prompts (GSM8K, AQuA).
humaneval        : CodeGen / HumanEval pass@k experiments (Sec. 3.3.1).
flops            : Inference FLOP computation (Electra-style) + pairing with results.
ancova           : ANCOVA regression analysis of FLOP vs performance (Sec. 4, App. C.2).
analysis         : Section 5 analyses: entropy, top-p overlap, P3 perplexity, logit diffs.
fudge            : FUDGE (Yang & Klein, 2021) baseline for toxicity/sentiment (Sec. 6).
negative_prompting : Section 3.4 assistant / negative prompting with GPT4All-J.
"""

__version__ = "0.1.0"
