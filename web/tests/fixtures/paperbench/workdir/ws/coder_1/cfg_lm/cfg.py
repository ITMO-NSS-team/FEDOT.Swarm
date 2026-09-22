"""Classifier-Free Guidance in logit space.

Implements Equation 7 of Section 2.2:

    log P_hat(w_i | w_{j<i}, c) =
        log P(w_i | w_{j<i})
        + gamma * ( log P(w_i | w_{j<i}, c) - log P(w_i | w_{j<i}) )

which is algebraically identical to the usual image-model formulation
(Equation 3, `x_hat = x_uncond + gamma * (x_cond - x_uncond)`) once applied
to logits instead of denoised pixels.

It also implements the *negative prompting* extension of Equation 5:

    log P_hat(w|c, c_neg) = log P(w|c)
        + gamma * ( log P(w|c) - log P(w|c_neg) )

where `c_neg` is an undesired conditioning prompt (e.g. the default system
prompt when steering towards an edited system prompt).

Section 3.1 detail implemented here: the unconditional pass is *not* an empty
sequence. The unconditional context starts at the **last token of the initial
prompt**, i.e. `log p(w_i | w_{j<i})` is evaluated on
`[prompt[-1]] + generated_tokens`, which keeps a minimal amount of local
context while dropping the conditioning prefix `c`.
"""

from typing import List, Optional, Tuple

import torch
import torch.nn.functional as F

__all__ = [
    "cfg_logits",
    "negative_cfg_logits",
    "unconditional_prefix",
    "CFGLogitsProcessor",
]


def cfg_logits(
    cond_logits: torch.Tensor,
    uncond_logits: torch.Tensor,
    guidance_strength: float = 1.0,
) -> torch.Tensor:
    """Apply Equation 7 to next-token logits.

    Parameters
    ----------
    cond_logits : torch.Tensor
        ``log P_theta(w_i | w_{j<i}, c)`` over the vocabulary, shape ``[..., V]``.
    uncond_logits : torch.Tensor
        ``log P_theta(w_i | w_{j<i})`` over the vocabulary, same shape. The
        unconditional context starts at the last token of the initial prompt
        (see :func:`unconditional_prefix`).
    guidance_strength : float
        Mutable guidance strength ``gamma``. ``gamma = 0`` returns the
        conditional logits (vanilla prompting); ``gamma = 1`` corresponds to
        the paper's ``P(w|c)`` reweighting with unit exponent.

    Returns
    -------
    torch.Tensor
        Guided log-probabilities ``log P_hat(w_i | w_{j<i}, c)``.
    """
    if guidance_strength == 0.0:
        return cond_logits
    return uncond_logits + guidance_strength * (cond_logits - uncond_logits)


def negative_cfg_logits(
    cond_logits: torch.Tensor,
    neg_cond_logits: torch.Tensor,
    guidance_strength: float = 1.0,
) -> torch.Tensor:
    """Equation 5 (negative prompting) in logit space.

    ``cond_logits`` is ``log P(w | c)`` for the desired (edited) system prompt
    and ``neg_cond_logits`` is ``log P(w | c_neg)`` for the negative/default
    prompt; both are computed on the same continuation.
    """
    if guidance_strength == 0.0:
        return cond_logits
    return cond_logits + guidance_strength * (cond_logits - neg_cond_logits)


def unconditional_prefix(
    prompt_token_ids: List[int], n_last_tokens: int = 1
) -> List[int]:
    """Context used for the unconditional pass (Section 3.1).

    "we implement CFG by starting the unconditional prompt at the last token of
    the initial prompt", i.e. ``w_{j<i}`` for ``log p_theta(w_i | w_{j<i})`` is
    seeded with the final token(s) of the prompt rather than the empty string.
    """
    if not prompt_token_ids:
        return []
    return list(prompt_token_ids[-n_last_tokens:])


class CFGLogitsProcessor:
    """Stateful helper that tracks guided generation for one batch element.

    Kept deliberately simple: it stores the prompt ids, the tokens generated so
    far and exposes the two model inputs (conditional / unconditional) needed
    for each decoding step.
    """

    def __init__(
        self,
        prompt_token_ids: List[int],
        guidance_strength: float = 1.0,
        n_uncond_prompt_tokens: int = 1,
    ) -> None:
        self.prompt = list(prompt_token_ids)
        self.guidance_strength = float(guidance_strength)
        self.n_uncond_prompt_tokens = n_uncond_prompt_tokens
        self.generated: List[int] = []

    # -- input construction -------------------------------------------------
    def conditional_input(self) -> List[int]:
        return self.prompt + self.generated

    def unconditional_input(self) -> List[int]:
        return unconditional_prefix(self.prompt, self.n_uncond_prompt_tokens) + self.generated

    # -- decoding -----------------------------------------------------------
    def combine(self, cond_logits: torch.Tensor, uncond_logits: torch.Tensor) -> torch.Tensor:
        return cfg_logits(cond_logits, uncond_logits, self.guidance_strength)

    def sample(
        self,
        cond_logits: torch.Tensor,
        uncond_logits: torch.Tensor,
        temperature: float = 1.0,
        top_p: float = 1.0,
        do_sample: bool = False,
    ) -> int:
        logits = self.combine(cond_logits, uncond_logits)
        if not do_sample:
            return int(torch.argmax(logits, dim=-1).item())
        logits = logits / max(temperature, 1e-8)
        if top_p < 1.0:
            logits = _top_p_filter(logits, top_p)
        probs = F.softmax(logits, dim=-1)
        return int(torch.multinomial(probs, num_samples=1).item())

    def step(self, token_id: int) -> None:
        self.generated.append(int(token_id))

    @property
    def sequence(self) -> Tuple[List[int], List[int]]:
        return self.prompt, self.generated


def _top_p_filter(logits: torch.Tensor, top_p: float) -> torch.Tensor:
    sorted_logits, sorted_idx = torch.sort(logits, descending=True)
    cumprobs = torch.cumsum(F.softmax(sorted_logits, dim=-1), dim=-1)
    remove = cumprobs > top_p
    remove[..., 1:] = remove[..., :-1].clone()
    remove[..., 0] = False
    idx_remove = remove.scatter(-1, sorted_idx, remove)
    return logits.masked_fill(idx_remove, float("-inf"))
