"""lm-evaluation-harness wrapper adding Classifier-Free Guidance (Eq. 7).

The paper runs Section 3.1's zero-shot benchmarks through EleutherAI's
Language Model Evaluation Harness (Gao et al., 2021).  This module provides
``CFGLMHarnessWrapper``, which wraps any harness ``BaseLM`` (or a HuggingFace
model/tokenizer pair) and rewrites the next-token log-probabilities according
to Equation 7:

    log P_hat = log P(w_i | w_{j<i}) + gamma * (log P(w_i | w_{j<i}, c) - log P(w_i | w_{j<i}))

with the unconditional pass started at the last token of the initial prompt
(Section 3.1).  The guidance strength ``gamma`` is a mutable hyper-parameter.

Usage with the harness CLI (once installed via ``pip install -e .``):

    lm_eval --model cfg-hf \
        --model_args pretrained=EleutherAI/pythia-160m,gamma=1.5 \
        --tasks lambada_openai,arc_challenge,arc_easy,boolq,hellaswag,\
piqa,sciq,triviaqa,winogrande \
        --batch_size 1

Works for the GPT2 family, the Pythia family, the LLaMA family, Guanaco-65B,
WizardLM-30B, CodeGen and Falcon models — anything AutoModelForCausalLM loads.
"""

from __future__ import annotations

import copy
from typing import List, Optional, Tuple

import torch
import torch.nn.functional as F

from .cfg import cfg_logits, unconditional_input_ids

try:  # optional dependency; module still importable without the harness
    from lm_eval.base import BaseLM
except Exception:  # pragma: no cover
    try:
        from lm_eval.api.model import LM as BaseLM  # newer API
    except Exception:
        BaseLM = object  # type: ignore


class CFGHFLM(BaseLM):  # type: ignore[misc]
    """Any HuggingFace causal LM, decoded with Classifier-Free Guidance."""

    def __init__(
        self,
        pretrained: str = "gpt2",
        gamma: float = 1.5,
        dtype: str = "float32",
        device: Optional[str] = None,
        max_length: int = 2048,
        trust_remote_code: bool = False,
        **kwargs,
    ):
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._max_length = max_length
        self.gamma = float(gamma)  # mutable guidance-strength hyper-parameter
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(
            pretrained, trust_remote_code=trust_remote_code
        )
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(
            pretrained, torch_dtype=dtype, trust_remote_code=trust_remote_code
        ).to(self.device)
        self.model.eval()

    # -- BaseLM interface -----------------------------------------------------
    @property
    def eot_token_id(self):
        return self.tokenizer.eos_token_id

    @property
    def max_gen_toks(self):
        return 32

    @property
    def vocab_size(self):
        return len(self.tokenizer)

    def tok_encode(self, string: str, **kw) -> List[int]:
        return self.tokenizer.encode(string, add_special_tokens=False)

    def tok_decode(self, tokens) -> str:
        return self.tokenizer.decode(tokens)

    # -- CFG forward ----------------------------------------------------------
    def _guided_last_logprobs(self, context_ids: List[int]) -> torch.Tensor:
        """Eq. 7 log-probs for the next token given conditional context ids.

        The unconditional distribution uses the context truncated to start at
        the LAST TOKEN of the initial prompt (Section 3.1).
        """
        ctx = torch.tensor([context_ids], device=self.device)
        with torch.no_grad():
            cond_lp = F.log_softmax(
                self.model(input_ids=ctx).logits[:, -1].float(), dim=-1
            )
            uncond_ctx = unconditional_input_ids(ctx)
            uncond_lp = F.log_softmax(
                self.model(input_ids=uncond_ctx).logits[:, -1].float(), dim=-1
            )
        return cfg_logits(cond_lp, uncond_lp, gamma=self.gamma)[0]

    def _last_logprobs_no_cfg(self, context_ids: List[int]) -> torch.Tensor:
        ctx = torch.tensor([context_ids], device=self.device)
        with torch.no_grad():
            lp = self.model(input_ids=ctx).logits[:, -1].float()
        return lp[0]

    # -- scoring used by multiple-choice tasks --------------------------------
    def score_sequence(self, context_ids: List[int], continuation_ids: List[int]) -> float:
        """Sum of guided log-probs over a teacher-forced continuation."""
        total = 0.0
        for i, tok in enumerate(continuation_ids):
            lp = self._guided_last_logprobs(context_ids + continuation_ids[:i])
            total += float(lp[tok])
        return total

    def loglikelihood_rolling(self, requests):
        raise NotImplementedError("Use loglikelihood for CFG multiple-choice eval.")

    def loglikelihood(self, requests):
        results: List[Tuple[float, bool]] = []
        for context, continuation in _iter_requests(requests):
            ctx_ids = self.tok_encode(context)
            # single-tokenize context+continuation to avoid boundary artifacts
            full_ids = self.tokenizer(
                context + continuation, add_special_tokens=False
            ).input_ids
            cont_ids = full_ids[len(ctx_ids):]
            if not cont_ids:
                results.append((0.0, False))
                continue
            tot = self.score_sequence(ctx_ids, cont_ids)
            is_greedy = True
            for i in range(len(cont_ids)):
                lp = self._guided_last_logprobs(ctx_ids + cont_ids[:i])
                if int(lp.argmax()) != cont_ids[i]:
                    is_greedy = False
                    break
            results.append((tot, is_greedy))
        return results

    def greedy_until(self, requests):
        out = []
        for req in _iter_requests(requests):
            context, until = req[0], req[2]
            text = self.generate_text(context, until=until)
            out.append((req[0], text))
        return out

    def generate_until(self, requests):
        return self.greedy_until(requests)

    # -- generation -----------------------------------------------------------
    @torch.no_grad()
    def generate_text(
        self,
        prompt: str,
        max_new_tokens: int = 128,
        temperature: float = 0.0,
        top_p: float = 1.0,
        until: Optional[List[str]] = None,
        gamma: Optional[float] = None,
    ) -> str:
        gamma = self.gamma if gamma is None else gamma
        ctx_ids = self.tok_encode(prompt)
        gen: List[int] = []
        for _ in range(max_new_tokens):
            lp = self._guided_last_logprobs_with_gamma(ctx_ids + gen, gamma)
            if temperature <= 0:
                tok = int(lp.argmax())
            else:
                probs = F.softmax(lp / temperature, dim=-1)
                tok = int(torch.multinomial(probs, 1).item())
            if tok == self.eot_token_id:
                break
            gen.append(tok)
            if until:
                text = self.tok_decode(gen)
                if any(u and u in text for u in until):
                    return text
        return self.tok_decode(gen)

    def _guided_last_logprobs_with_gamma(self, context_ids, gamma):
        ctx = torch.tensor([context_ids], device=self.device)
        cond_lp = F.log_softmax(
            self.model(input_ids=ctx).logits[:, -1].float(), dim=-1
        )
        uncond_lp = F.log_softmax(
            self.model(input_ids=unconditional_input_ids(ctx)).logits[:, -1].float(),
            dim=-1,
        )
        return cfg_logits(cond_lp, uncond_lp, gamma=gamma)[0]


def _iter_requests(requests):
    """Normalize harness request formats (tuple or Instance objects)."""
    for req in requests:
        if isinstance(req, tuple):
            yield req
        else:  # lm_eval.api.instance.Instance
            args = getattr(req, "args", req)
            yield args


# ---------------------------------------------------------------------------
# Registration hook for `lm_eval --model cfg-hf`
# ---------------------------------------------------------------------------

def register():
    """Register this LM with the harness registry when available."""
    try:
        from lm_eval.api.registry import register_model
    except Exception:
        return
    register_model("cfg-hf")(CFGHFLM)


register()
