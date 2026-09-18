"""Core Classifier-Free Guidance for autoregressive language models.

Implements Equation 7 of Section 2.2:

    log P_hat(w_i | w_{j<i}, c) = log P(w_i | w_{j<i})
        + gamma * ( log P(w_i | w_{j<i}, c) - log P(w_i | w_{j<i}) )

i.e. the conditional logits are extrapolated away from the unconditional
("null prompt") logits with guidance strength ``gamma``.  gamma = 1 recovers
vanilla conditional decoding; gamma = 0 recovers pure unconditional decoding.

Following Section 3.1, the unconditional distribution log p_theta(w_i | w_{j<i})
is *started at the last token of the initial prompt*: the unconditional context
is the single last token of the prompt, and it is extended with each generated
token.  This keeps the unconditional continuation locally coherent while still
removing the prompt conditioning.

Negative prompting (Equation 5 applied to LMs, Section 3.4) contrasts a
positive condition c against a negative condition c_neg:

    log P_hat = log P(w | c_neg) + gamma * (log P(w | c) - log P(w | c_neg))
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import torch
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Pure tensor-level CFG operations (usable with any model backend)
# ---------------------------------------------------------------------------

def cfg_logits(
    cond_logits: torch.Tensor,
    uncond_logits: torch.Tensor,
    gamma: float = 1.5,
) -> torch.Tensor:
    """Apply CFG in logit space (Eq. 7).

    log P_hat = log P_uncond + gamma * (log P_cond - log P_uncond)

    Works on raw logits or log-probabilities; both are linear in the update.

    Args:
        cond_logits:   logits/logprobs conditioned on the prompt c.
        uncond_logits: logits/logprobs of the unconditional pass.
        gamma:         guidance strength (mutable hyper-parameter).
    """
    return uncond_logits + gamma * (cond_logits - uncond_logits)


def negative_prompt_cfg_logits(
    pos_logits: torch.Tensor,
    neg_logits: torch.Tensor,
    gamma: float = 3.0,
) -> torch.Tensor:
    """CFG with an explicit negative prompt (Eq. 5 / Section 3.4).

    log P_hat = log P(w | c_neg) + gamma * (log P(w | c) - log P(w | c_neg))
    """
    return cfg_logits(pos_logits, neg_logits, gamma=gamma)


def sample_token(
    logits: torch.Tensor,
    temperature: float = 1.0,
    top_p: float = 1.0,
    rng: Optional[torch.Generator] = None,
) -> torch.Tensor:
    """Temperature / nucleus sampling from a (batched) logits vector."""
    if temperature <= 0:
        return logits.argmax(dim=-1, keepdim=True)
    probs = F.softmax(logits / temperature, dim=-1)
    if top_p < 1.0:
        sorted_probs, sorted_idx = torch.sort(probs, descending=True, dim=-1)
        cumsum = sorted_probs.cumsum(dim=-1)
        mask = cumsum - sorted_probs > top_p
        sorted_probs = sorted_probs.masked_fill(mask, 0.0)
        sorted_probs = sorted_probs / sorted_probs.sum(dim=-1, keepdim=True)
        idx = torch.multinomial(sorted_probs, 1, generator=rng)
        return torch.gather(sorted_idx, -1, idx)
    return torch.multinomial(probs, 1, generator=rng)


# ---------------------------------------------------------------------------
# Unconditional-context construction (Section 3.1)
# ---------------------------------------------------------------------------

def unconditional_input_ids(prompt_ids: torch.Tensor) -> torch.Tensor:
    """Build the unconditional sequence from a prompt.

    As outlined in Section 3.1, the unconditional prompt starts at the LAST
    TOKEN of the initial prompt: ``uncond = [prompt[-1]]``.  During generation
    the sampled tokens are appended to this short context exactly as they are
    to the conditional context.
    """
    return prompt_ids[..., -1:]


# ---------------------------------------------------------------------------
# HuggingFace causal LM wrapper implementing Eq. 7 for generation
# ---------------------------------------------------------------------------

class CFGGenerator:
    """Classifier-Free Guidance decoding for any HuggingFace causal LM.

    Model families used in the paper that work out of the box with this class:
      * GPT-2 family            ("gpt2", "gpt2-medium", ...)
      * Pythia family           ("EleutherAI/pythia-*")
      * LLaMA family            ("huggyllama/llama-*")
      * Guanaco-65B             ("TheBloke/Guanaco-65B-GPTQ", LLaMA arch)
      * WizardLM-30B            ("WizardLM/WizardLM-30B-V1.0", LLaMA arch)
      * CodeGen family          ("Salesforce/codegen-*-mono")
      * Falcon family           ("tiiuae/falcon-7b-base" / "-instruct")
      * GPT4All-J               ("nomic-ai/gpt4all-j", GPT-J arch)

    The guidance strength ``gamma`` is a mutable attribute / constructor
    argument — never hardcoded.
    """

    def __init__(
        self,
        model,
        tokenizer,
        gamma: float = 1.5,
        device: Optional[str] = None,
    ):
        self.model = model
        self.tokenizer = tokenizer
        self.gamma = gamma  # mutable guidance-strength hyper-parameter
        self.device = device or next(model.parameters()).device

    # -- forward passes ------------------------------------------------------
    @torch.no_grad()
    def _next_logprobs(self, input_ids: torch.Tensor) -> torch.Tensor:
        """Log-probs over the vocabulary for the token *following* input_ids."""
        out = self.model(input_ids=input_ids)
        logits = out.logits[:, -1, :]  # (batch, vocab)
        return F.log_softmax(logits.float(), dim=-1)

    @torch.no_grad()
    def _distribute(self, input_ids: torch.Tensor):
        """Return (past_key_values_cond, past_key_values_uncond) style state.

        We recompute without kv-cache by default for simplicity and exactness;
        callers can pass longer contexts.  Returns full-sequence log-probs.
        """
        out = self.model(input_ids=input_ids)
        logits = out.logits.float()
        return F.log_softmax(logits, dim=-1)

    # -- generation loop -----------------------------------------------------
    @torch.no_grad()
    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 32,
        temperature: float = 0.0,
        top_p: float = 1.0,
        gamma: Optional[float] = None,
        eos_token_id: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        return_raw: bool = False,
    ) -> str:
        """Generate a continuation of ``prompt`` using CFG (Eq. 7).

        Args:
            prompt: the conditioning text c.
            gamma: guidance strength for this call; defaults to self.gamma.
            negative_prompt: if given, use Eq.-5 negative prompting instead of
                the last-token unconditional baseline (Section 3.4).
        """
        gamma = self.gamma if gamma is None else gamma
        enc = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        cond_ids = enc.input_ids
        # Section 3.1: unconditional prompt starts at the last prompt token.
        uncond_ids = unconditional_input_ids(cond_ids)

        gen = []
        for _ in range(max_new_tokens):
            cond_lp = self._next_logprobs(cond_ids)
            uncond_lp = self._next_logprobs(uncond_ids)
            guided = cfg_logits(cond_lp, uncond_lp, gamma=gamma)
            tok = sample_token(guided, temperature=temperature, top_p=top_p)
            if eos_token_id is not None and int(tok) == int(eos_token_id):
                break
            gen.append(int(tok))
            cond_ids = torch.cat([cond_ids, tok], dim=-1)
            uncond_ids = torch.cat([uncond_ids, tok], dim=-1)

        text = self.tokenizer.decode(gen, skip_special_tokens=True)
        if return_raw:
            return text, gen
        return text

    # -- scoring (for likelihood-based benchmarks) ----------------------------
    @torch.no_grad()
    def score_continuation(
        self,
        prompt: str,
        continuation: str,
        gamma: Optional[float] = None,
    ) -> float:
        """Total log-prob of ``continuation`` under CFG-guided decoding.

        Used by the harness for multiple-choice tasks: each answer choice is
        scored with guided teacher forcing (Eq. 7 applied per position).
        """
        gamma = self.gamma if gamma is None else gamma
        p_ids = self.tokenizer(prompt, add_special_tokens=False).input_ids
        c_ids = self.tokenizer(continuation, add_special_tokens=False).input_ids
        if len(c_ids) == 0:
            return 0.0
        total = 0.0
        # Conditional context: prompt + so-far; unconditional context starts at
        # the last token of the initial prompt (Section 3.1) and grows.
        for i, tok in enumerate(c_ids):
            cond_ctx = torch.tensor([p_ids + c_ids[:i]], device=self.device)
            uncond_ctx = torch.tensor([[p_ids[-1]] + c_ids[:i]], device=self.device)
            cond_lp = self._next_logprobs(cond_ctx)[0]
            uncond_lp = self._next_logprobs(uncond_ctx)[0]
            guided = cfg_logits(cond_lp.unsqueeze(0), uncond_lp.unsqueeze(0), gamma)
            total += float(guided[0, tok])
        return total


# ---------------------------------------------------------------------------
# Token-level logit-difference visualization (Section 5.3, Table 3)
# ---------------------------------------------------------------------------

def logit_differences(
    generator: CFGGenerator,
    prompt: str,
    generated_tokens: List[int],
    top_k: int = 5,
) -> List[Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]]:
    """Rank the vocabulary by log P(w_t|w_<t) - log P(w_t|w_hat) per step.

    Section 5.3: shows which tokens CFG upweights (top-k) and downweights
    (bottom-k) at each generation step.
    """
    enc = generator.tokenizer(prompt, return_tensors="pt").to(generator.device)
    cond_ids = enc.input_ids
    uncond_ids = unconditional_input_ids(cond_ids)
    steps = []
    for tok in generated_tokens:
        cond_lp = generator._next_logprobs(cond_ids)[0]
        uncond_lp = generator._next_logprobs(uncond_ids)[0]
        diff = cond_lp - uncond_lp  # log P(w|w<t,c) - log P(w|w~)
        topv, topi = diff.topk(top_k)
        botv, boti = diff.topk(top_k, largest=False)
        steps.append((
            list(zip(topi.tolist(), topv.tolist())),
            list(zip(boti.tolist(), botv.tolist())),
        ))
        t = torch.tensor([[tok]], device=generator.device)
        cond_ids = torch.cat([cond_ids, t], dim=-1)
        uncond_ids = torch.cat([uncond_ids, t], dim=-1)
    return steps
