# Workspace of coder_0

Reproduce the code of this paper in your workspace. The paper begins:

## Stay on topic with Classifier-Free Guidance

Guillaume V. Sanchez \* 1 2 Alexander Spangher \* 3 Honglu Fan \* 4 2 Elad Levi <sup>5</sup> Stella Biderman <sup>2</sup>

## Abstract

Classifier-Free Guidance (CFG) has recently emerged in as a lightweight technique to encourage prompt-adherence in generations, yet has not yet been successfully applied to language modeling. In this work, we demonstrate across a wide array of benchmarks that CFG can be used broadly as an inference-time technique in pure language modeling. We show that CFG (1) improves the performance of Pythia, GPT-2 and LLaMAfamily models across a broad set of Q&A, reasoning and code generation tasks, achieving SOTA on LAMBADA with LLaMA-7B over PaLM-540B; (2) brings improvements equivalent to a model with twice the parameter-count; (3) can stack alongside other inference-time methods like Chain-of-Thought and Self-Consistency, yielding further improvements in difficult tasks; (4) can be used to increase the faithfulness and coherence of assistants in challenging form-driven and contentdriven prompts: in human evaluations we show a 75% preference for using CFG over baseline.

## 1. Introduction

In recent years, large language models (LLMs) have exhibited strong capabilities on a diverse array of tasks [\(Devlin](#page-9-0) [et al., 2019b;](#page-9-0) [Brown et al., 2020;](#page-9-1) [Scao et al., 2022\)](#page-12-0). However, they continue struggle with issues such as hallucination [\(Manakul et al., ...

The full text is in paper.md and the grading rubric in rubric.md, both in your working directory. The branch under review: The core contributions of the paper have been reproduced.

Do not run training, do not download any dataset or pretrained weights, and do not access the paper's own repository.

The rubric's 70 leaves, graded by reading your code, start with:
- Code has been implemented such that the zero-shot benchmark dataset ARC-c (https://huggingface.co/datasets/allenai/ai2_arc) can be used, obtaining it from its official source or equivalent mirrors
- Code has been implemented such that the zero-shot benchmark dataset ARC-e (https://huggingface.co/datasets/allenai/ai2_arc) can be used, obtaining it from its official source or equivalent mirrors
- Code has been implemented such that the zero-shot benchmark dataset BoolQ (https://huggingface.co/datasets/google/boolq) can be used, obtaining it from its official source or equivalent mirrors
- Code has been implemented such that the zero-shot benchmark dataset HellaSwag (https://rowanzellers.com/hellaswag/) can be used, obtaining it from its official source or equivalent mirrors
- Code has been implemented such that the zero-shot benchmark dataset PiQA (https://github.com/ybisk/ybisk.github.io/tree/master/piqa) can be used, obtaining it from its official source or equivalent mirrors
- Code has been implemented such that the zero-shot benchmark dataset SciQ (https://huggingface.co/datasets/allenai/sciq) can be used, obtaining it from its official source or equivalent mirrors
- Code has been implemented such that the zero-shot benchmark dataset TriviaQA (https://huggingface.co/datasets/mandarjoshi/trivia_qa) can be used, obtaining it from its official source or equivalent mirrors
- Code has been implemented such that the zero-shot benchmark dataset WinoGrande (https://huggingface.co/datasets/allenai/winogrande) can be used, obtaining it from its official source or equivalent mirrors
- Code has been implemented such that the zero-shot benchmark dataset Lambada (https://huggingface.co/datasets/EleutherAI/lambada_openai) can be used, obtaining it from its official source or equivalent mirrors
- The evaluation harness has been reproduced, either by directly using the Language Model Evaluation Harness (Gao et al., 2021, github.com/EleutherAI/lm-evaluation-harness) or by reproducing the Language Model Evaluation Harness
- Classifier-Free Guidance (CFG) inference is implemented as described in equation 7 in Section 2.2 such that it can be run on the GPT2 family of models
- The implementation of CFG which can be used for the GPT2 family of models includes a mutable (not hardcoded) hyper-parameter which can be used to specify the guidance strength
- As outlined in Section 3.1, the implementation of CFG which can be used for the GPT2 family of models starts the unconditional prompt $\log p_{\theta}(w_i | w_{j < i})$ with the last token of the initial prompt
- Classifier-Free Guidance (CFG) inference is implemented as described in equation 7 in Section 2.2 such that it can be run on the Pythia family of models
- The implementation of CFG which can be used for the Pythia family of models includes a mutable (not hardcoded) hyper-parameter which can be used to specify the guidance strength
- As outlined in Section 3.1, the implementation of CFG which can be used for the Pythia family of models starts the unconditional prompt $\log p_{\theta}(w_i | w_{j < i})$ with the last token of the initial prompt
- Code has been implemented such that the GSM8K dataset for arithmetic reasoning tasks (https://huggingface.co/datasets/openai/gsm8k) can be used, obtaining it from its official source or equivalent mirrors
- Code has been implemented such that the AQuA dataset for arithmetic reasoning tasks (https://huggingface.co/datasets/nguyen-brat/aqua) can be used, obtaining it from its official source or equivalent mirrors
- Classifier-Free Guidance (CFG) inference is implemented as described in equation 7 in Section 2.2 such that it can be run on the Guanaco65B model.
- The implementation of CFG which can be used for the Guanaco65B model includes a mutable (not hardcoded) hyper-parameter which can be used to specify the guidance strength
- ... and 50 more in rubric.md

paper.md, paper_outline.md and rubric.md are read-only inputs; everything else is yours.
