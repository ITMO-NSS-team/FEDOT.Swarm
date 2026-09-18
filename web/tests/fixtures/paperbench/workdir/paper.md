## Stay on topic with Classifier-Free Guidance

Guillaume V. Sanchez \* 1 2 Alexander Spangher \* 3 Honglu Fan \* 4 2 Elad Levi <sup>5</sup> Stella Biderman <sup>2</sup>

## Abstract

Classifier-Free Guidance (CFG) has recently emerged in as a lightweight technique to encourage prompt-adherence in generations, yet has not yet been successfully applied to language modeling. In this work, we demonstrate across a wide array of benchmarks that CFG can be used broadly as an inference-time technique in pure language modeling. We show that CFG (1) improves the performance of Pythia, GPT-2 and LLaMAfamily models across a broad set of Q&A, reasoning and code generation tasks, achieving SOTA on LAMBADA with LLaMA-7B over PaLM-540B; (2) brings improvements equivalent to a model with twice the parameter-count; (3) can stack alongside other inference-time methods like Chain-of-Thought and Self-Consistency, yielding further improvements in difficult tasks; (4) can be used to increase the faithfulness and coherence of assistants in challenging form-driven and contentdriven prompts: in human evaluations we show a 75% preference for using CFG over baseline.

## 1. Introduction

In recent years, large language models (LLMs) have exhibited strong capabilities on a diverse array of tasks [\(Devlin](#page-9-0) [et al., 2019b;](#page-9-0) [Brown et al., 2020;](#page-9-1) [Scao et al., 2022\)](#page-12-0). However, they continue struggle with issues such as hallucination [\(Manakul et al., 2023\)](#page-11-0), degradation [\(Holtzman et al.,](#page-10-0) [2019\)](#page-10-0) and meandering [\(Spangher et al., 2023\)](#page-12-1). Various approaches have been proposed to address this, like instructionfinetuning [\(Wei et al., 2021;](#page-12-2) [Sanh et al., 2021\)](#page-12-3) and reinforcement learning [\(Ouyang et al., 2022a;](#page-11-1) [Askell et al., 2021\)](#page-8-0), however, these techniques require large amounts of data and

Figure 1: An illustration in latent space showing how increasing the guidance weight γ increases the importance of the prompt "Today in France,".

may not be accessible to all researchers.

Meanwhile, similar degenerative problems have been observed in text-to-image-generation: models can ignore parts of the prompt or introduce extra objects [\(Nichol et al., 2022\)](#page-11-2). Classifier-Free Guidance (CFG) has emerged as an elegant *training-free* approach to address this [\(Ho & Salimans,](#page-10-1) [2021\)](#page-10-1). In CFG, the generative model *itself* is used *sans modifications* during inference to encourage desirata.

While CFG might be a lightweight solution to promptmisadherence in LLMs, it has not previously been applied in the autoregressive text-generation setting. There are many reasons to hypothesize CFG might *not* transfer: in text-toimage generation, the prompts are simple descriptions and outputs are fixed-size [\(Lin et al., 2023\)](#page-10-2). In language modeling, prompts can be highly complex and multipart, and outputs are autoregressive and unbounded.

In this paper, we apply CFG to LLMs to increase the model alignment to prompts. We perform modifications to CFG: while text-to-image models (which primarily utilize diffusion models) need to be specifically trained with conditioning dropout [\(Ho & Salimans, 2021\)](#page-10-1) to utilize CFG, we find that in text generation, CFG can work out-of-thebox, at lower γ values (we discuss more in Section [6\)](#page-6-0). CFG improves alignment on an exhaustive array of benchmarks covering, we show, many widely used prompting

<sup>\*</sup>Equal contribution <sup>1</sup>LightOn, France (work done while working at Hexaglobe) <sup>2</sup>EleutherAI <sup>3</sup> Information Sciences Institute, University of Southern California <sup>4</sup>University of Geneva 5 Sightful. Correspondence to: Guillaume V. Sanchez <guillaume.sanchez@lighton.ai>, Honglu Fan <honglu.fan@unige.ch>, Alexander Spangher <spangher@usc.edu>.

approaches: *zero-shot prompting, Chain-of-Thought prompting, long-form generative prompting* and complex chatbotstyle prompting (see Table [1\)](#page-2-0). Not only is our formulation of CFG effective and lightweight, it is *remarkably stable* to hyperparameter settings and requires no tuning across prompting styles: it is a promising plug-and-play technique. Our work has been directly incorporated into leading opensource libraries: Huggingface and llama.cpp.

We make the following contributions:

- 1. We devise a framework for CFG in language modeling and show significant improvements across a range of benchmarks, establishing it as a versatile *inferencetime technique that can be applied out-of-the-box*. We test CFG in many different prompting techniques spanning many LLM use-cases, even *achieving SOTA* on LAMBADA with LLaMA-7B over PaLM-540B [\(Chowdhery et al., 2022\)](#page-9-2).
- 2. We show that for the same computational costs during inference-time, in terms of FLOPs and VRAM, one can use CFG to train a model that is half the size and obtain similar performance on those benchmarks;
- 3. By using negative prompting, we demonstrate that we can achieve more granular control over Chatbot-style assistant prompting. In a blind human evaluation we show 75% preference for GPT4All using CFG in this setting over the vanilla sampling;
- 4. We provide interpretations for the impact that CFG on text generation both (1) qualitatively, by visualizing how CFG is upweighting words more related to the prompt (our visualization, we note, can be an integral part of effective prompt engineering) and (2) quantitatively, by showing that CFG decreases entropy in the sampling distribution.

## 2. Background and Related Works

To understand Classifier-Free Guidance (CFG) in LLMs, we must first understand steering and controllability in generative models. In this section, we first discuss the origins of CFG in text-to-image generation, and then discuss how autoregressive language modeling differs.

## <span id=

[cut for the fixture]
