"""Classifier-Free Guidance (CFG) for autoregressive language models.

Reproduction of the code in "Stay on topic with Classifier-Free Guidance"
(Sanchez, Spangher, Fan, Levi, Biderman).

Modules
-------
cfg        : Equation 7 / Equation 5 logit-level classifier-free guidance.
wrappers   : HuggingFace `LM` adapters used by the evaluation harness
             (GPT-2, Pythia, LLaMA / Guanaco / WizardLM, CodeGen, Falcon, GPT4All).
harness    : A self-contained reproduction of the EleutherAI Language Model
             Evaluation Harness (Gao et al., 2021) likelihood metrics.
tasks      : Zero-shot benchmark task definitions (ARC-c/e, BoolQ, HellaSwag,
             PiQA, SciQ, TriviaQA, WinoGrande, LAMBADA).
cot        : Chain-of-Thought GSM8K / AQuA evaluation (Section 3.2).
humaneval  : Program synthesis evaluation with pass@k (Section 3.3.1).
flops      : Electra-style inference FLOP counting + ANCOVA analysis (Section 4).
analysis   : Entropy / top-p overlap / perplexity / logit-diff visualisation (Section 5).
fudge      : FUDGE baseline for classifier guidance comparison (Section 6).
chatbot    : Negative prompting with GPT4All-J (Section 3.4).
toxicity   : Toxicity / sentiment control experiments (Section 6).
"""

__version__ = "1.0.0"
