"""HuggingFace model wrappers implementing Classifier-Free Guidance (Eq. 7).

Each wrapper exposes the small surface used by our harness reproduction
(``cfg_lm.harness``) and is also importable from lm-evaluation-harness via
``lm_eval --model hf_cfg`` style entry points (see ``harness.py``).

Model families covered (paper Sections 3.1-3.4, 5):

* GPT-2 family            -> ``CFG_GPT2``            (nlp/gpt2{,-medium,-large,-xl})
* Pythia family           -> ``CFG_Pythia``          (EleutherAI/pythia.*)
* LLaMA family            -> ``CFG_LLaMA``           (huggyllama/llama-*)
* Guanaco-65B             -> ``CFG_Guanaco65B``      (TheBloke/Guanaco-65B-GPT4All)
* WizardLM-30B            -> ``CFG_WizardLM30B``     (WizardLM/WizardLM-30B-V1.0)
* CodeGen family          -> ``CFG_CodeGen``         (Salesforce/codegen-{350m,2b,6b}-mono)
* Falcon base / instruct  -> ``CFG_Falcon7bBase`` / ``CFG_Falcon7bInstruct``
* GPT4All-J               -> ``CFG_GPT4AllJ``        (nomic-ai/gpt4all-j)

Key implementation detail from Section 3.1:
    "we implement CFG by starting the unconditional prompt at the last token
     of the initial prompt"
i.e. the unconditional pass conditions only on ``prompt[-1]`` plus the tokens
generated so far; the conditioning prefix ``c`` is dropped. This is done in
:meth:`CFGWrapper.generate_with_cfg` for every family uniformly.

Guidance strength ``gamma`` is a *mutable instance attribute* (also settable
per call), never hardcoded: it can be swept over e.g. [1, 1.1, 1.25, 1.5,
1.75, 2] (Figure 2 / Footnote 3).
"""

from typing import Dict, List, Optional, Tuple

import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer

from .cfg import cfg_logits, negative_cfg_logits, unconditional_prefix

__all__ = [
    "CFGWrapper",
    "CFG_GPT2",
    "CFG_Pythia",
    "CFG_LLaMA",
    "CFG_Guanaco65B",
    "CFG_WizardLM30B",
    "CFG_CodeGen",
    "CFG_Falcon7bBase",
    "CFG_Falcon7bInstruct",
    "CFG_Falcon",
    "CFG_GPT4AllJ",
    "MODEL_REGISTRY",
]


class CFGWrapper:
    """Autoregressive LM with next-token classifier-free guidance (Eq. 7).

    Parameters
    ----------
    model_name : str
        HuggingFace hub id or local path.
    guidance_strength : float
        Mutable gamma hyper-parameter (Section 2.2, Eq. 7). Settable at
        construction time, per generation call, or via attribute assignment.
    device, dtype : passed through to ``from_pretrained``.
    n_uncond_prompt_tokens : int
        How many trailing prompt tokens seed the unconditional context
        (default 1, exactly as described in Section 3.1).
    """

    def __init__(
        self,
        model_name: str,
        guidance_strength: float = 1.5,
        device: Optional[str] = None,
        dtype=torch.float16,
        trust_remote_code: bool = False,
        n_uncond_prompt_tokens: int = 1,
        max_length: Optional[int] = None,
    ) -> None:
        self.model_name = model_name
        self.guidance_strength = float(guidance_strength)
        self.n_uncond_prompt_tokens = n_uncond_prompt_tokens
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, trust_remote_code=trust_remote_code
        )
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.add_special_tokens({"pad_token": "[PAD]"})
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=dtype,
            trust_remote_code=trust_remote_code,
            device_map="auto" if device is None else None,
        )
        if device is not None:
            self.model.to(device)
        self.model.eval()

    # ------------------------------------------------------------------ util
    @torch.no_grad()
    def _next_token_logits(self, token_ids: List[int]) -> torch.Tensor:
        """log P_theta(w_i | w_{j<i}) over the vocabulary for one context."""
        input_ids = torch.tensor([token_ids], device=self.model.device)
        logits = self.model(input_ids=input_ids).logits[0, -1]
        return torch.log_softmax(logits.float(), dim=-1)

    def set_guidance_strength(self, gamma: float) -> None:
        """Mutable guidance strength (never hardcoded)."""
        self.guidance_strength = float(gamma)

    # ------------------------------------------------------------- decoding
    @torch.no_grad()
    def generate_with_cfg(
        self,
        prompt: str,
        max_new_tokens: int = 32,
        guidance_strength: Optional[float] = None,
        temperature: float = 1.0,
        top_p: float = 1.0,
        do_sample: bool = False,
        eos_token: Optional[str] = None,
    ) -> str:
        """Greedy/sampled generation guided by Equation 7.

        The conditional context is the full prompt + continuation; the
        unconditional context starts at the *last token of the prompt*
        (Section 3.1).
        """
        gamma = self.guidance_strength if guidance_strength is None else float(guidance_strength)
        prompt_ids = self.tokenizer(prompt, return_tensors="pt").input_ids[0].tolist()
        uncond_seed = unconditional_prefix(prompt_ids, self.n_uncond_prompt_tokens)
        generated: List[int] = []
        eos_id = self.tokenizer.convert_tokens_to_ids(eos_token) if eos_token else self.tokenizer.eos_token_id

        for _ in range(max_new_tokens):
            cond_lp = self._next_token_logits(prompt_ids + generated)
            uncond_lp = self._next_token_logits(uncond_seed + generated)
            guided = cfg_logits(cond_lp, uncond_lp, gamma)
            if do_sample:
                probs = F.softmax(guided / max(temperature, 1e-8), dim=-1)
                if top_p < 1.0:
                    probs = _top_p_mask(probs, top_p)
                next_id = int(torch.multinomial(probs, num_samples=1).item())
            else:
                next_id = int(torch.argmax(guided, dim=-1).item())
            if eos_id is not None and next_id == eos_id:
                break
            generated.append(next_id)
        return self.tokenizer.decode(generated, skip_special_tokens=True)

    # --------------------------------------------------- loglikelihood (harness)
    @torch.no_grad()
    def score_continuation_with_cfg(
        self,
        context: str,
        continuation: str,
        guidance_strength: Optional[float] = None,
    ) -> float:
        """Sum of CFG-guided log-probs of the continuation tokens.

        Used for likelihood-based zero-shot tasks (multiple choice, LAMBADA):
        each candidate answer is scored under the guided distribution
        ``log \\hat P(w_i | w_{j<i}, c)`` of Equation 7.
        """
        gamma = self.guidance_strength if guidance_strength is None else float(guidance_strength)
        ctx_ids = self.tokenizer(context, return_tensors="pt").input_ids[0].tolist()
        cont_ids = self.tokenizer(continuation, add_special_tokens=False, return_tensors="pt").input_ids[0].tolist()
        uncond_seed = unconditional_prefix(ctx_ids, self.n_uncond_prompt_tokens)
        total = 0.0
        for i, tok in enumerate(cont_ids):
            cond_lp = self._next_token_logits(ctx_ids + cont_ids[:i])
            uncond_lp = self._next_token_logits(uncond_seed + cont_ids[:i])
            guided = cfg_logits(cond_lp, uncond_lp, gamma)
            total += float(guided[tok].item())
        return total

    def loglikelihood(self, context: str, continuation: str) -> Tuple[float, bool]:
        """Harness-style API: (logprob, is_greedy) for teacher-forced scoring."""
        gamma = self.guidance_strength
        ctx_ids = self.tokenizer(context, return_tensors="pt").input_ids[0].tolist()
        enc_cont = self.tokenizer(continuation, add_special_tokens=False).input_ids
        # re-tokenize to align greedy prefix like the harness does
        joined = self.tokenizer(context + continuation).input_ids[len(ctx_ids):]
        cont_ids = joined if len(joined) >= 1 else enc_cont
        uncond_seed = unconditional_prefix(ctx_ids, self.n_uncond_prompt_tokens)
        total, is_greedy = 0.0, True
        for i, tok in enumerate(cont_ids):
            cond_lp = self._next_token_logits(ctx_ids + cont_ids[:i])
            uncond_lp = self._next_token_logits(uncond_seed + cont_ids[:i])
            guided = cfg_logits(cond_lp, uncond_lp, gamma)
            total += float(guided[tok].item())
            if int(torch.argmax(guided, dim=-1).item()) != tok:
                is_greedy = False
        return total, is_greedy

    def loglikelihood_rolling(self, text: str) -> float:
        """Perplexity-oriented API: plain (unguided) logprob of `text`."""
        ids = self.tokenizer(text, return_tensors="pt").input_ids[0].tolist()
        total = 0.0
        for i in range(1, len(ids)):
            lp = self._next_token_logits(ids[:i])
            total += float(lp[ids[i]].item())
        return total

    # ------------------------------------------------------ full-vocab deltas
    @torch.no_grad()
    def cfg_logit_differences(
        self,
        prompt: str,
        continuation_ids: List[int],
        guidance_strength: Optional[float] = None,
    ) -> List[torch.Tensor]:
        """Per-step full-vocabulary deltas used for Section 5.3 visualisation:

        ``log P(w_t | w_{<t}) - log P(w_T | \\hat w)`` evaluated across the
        whole vocabulary at each generation step, where the second term is
        the unconditional (uncued) estimate started from the last prompt
        token. Returns one tensor of shape [V] per step.
        """
        gamma = self.guidance_strength if guidance_strength is None else float(guidance_strength)
        ctx_ids = self.tokenizer(prompt, return_tensors="pt").input_ids[0].tolist()
        uncond_seed = unconditional_prefix(ctx_ids, self.n_uncond_prompt_tokens)
        deltas: List[torch.Tensor] = []
        for i, tok in enumerate(continuation_ids):
            cond_lp = self._next_token_logits(ctx_ids + continuation_ids[:i])
            uncond_lp = self._next_token_logits(uncond_seed + continuation_ids[:i])
            guided = cfg_logits(cond_lp, uncond_lp, gamma)
            deltas.append(guided - uncond_lp)
        return deltas


def _top_p_mask(probs: torch.Tensor, top_p: float) -> torch.Tensor:
    sorted_probs, sorted_idx = torch.sort(probs, descending=True)
    cum = torch.cumsum(sorted_probs, dim=-1)
    remove = cum > top_p
    remove[..., 1:] = remove[..., :-1].clone()
    remove[..., 0] = False
    keep = ~remove.scatter(-1, sorted_idx, remove)
    return probs * keep


# ------------------------------------------------------------------ families
class CFG_GPT2(CFGWrapper):
    """GPT-2 small/medium/large/xl (paper Table 5 rows G-s..G-xl)."""

    DEFAULT = "gpt2"

    def __init__(self, model_name: str = "gpt2", **kwargs) -> None:
        super().__init__(model_name, **kwargs)


class CFG_Pythia(CFGWrapper):
    """Pythia 160M-12B family (Table 5 rows P-*)."""

    def __init__(self, model_name: str = "EleutherAI/pythia-410m", **kwargs) -> None:
        super().__init__(model_name, **kwargs)


class CFG_LLaMA(CFGWrapper):
    """LLaMA-1 family 7B/13B/30B/65B (Table 5 rows L-*)."""

    def __init__(self, model_name: str = "huggyllama/llama-7b", **kwargs) -> None:
        super().__init__(model_name, **kwargs)


class CFG_Guanaco65B(CFGWrapper):
    """Guanaco-65B (Dettmers et al., 2023) for CoT GSM8K/AQuA (Section 3.2)."""

    def __init__(self, model_name: str = "TheBloke/guanaco-65B-GPT4True", **kwargs) -> None:
        kwargs.setdefault("guidance_strength", 1.25)
        super().__init__(model_name, **kwargs)


class CFG_WizardLM30B(CFGWrapper):
    """WizardLM-30B (Xu et al., 2023) for CoT GSM8K/AQuA (Section 3.2)."""

    def __init__(self, model_name: str = "WizardLM/WizardLM-30B-V1.0", **kwargs) -> None:
        kwargs.setdefault("guidance_strength", 1.25)
        super().__init__(model_name, **kwargs)


class CFG_CodeGen(CFGWrapper):
    """CodeGen mono family 350M/2B/6B for HumanEval (Section 3.3.1)."""

    def __init__(self, model_name: str = "Salesforce/codegen-350M-mono", **kwargs) -> None:
        kwargs.setdefault("guidance_strength", 1.25)
        super().__init__(model_name, **kwargs)


class CFG_Falcon(CFGWrapper):
    """Falcon-7b variants used in the Section 5 analysis."""

    def __init__(self, model_name: str = "tiiuae/falcon-7b", **kwargs) -> None:
        kwargs.setdefault("trust_remote_code", True)
        super().__init__(model_name, **kwargs)


class CFG_Falcon7bBase(CFG_Falcon):
    DEFAULT = "tiiuae/falcon-7b"

    def __init__(self, model_name: str = "tiiuae/falcon-7b", **kwargs) -> None:
        super().__init__(model_name, **kwargs)


class CFG_Falcon7bInstruct(CFG_Falcon):
    DEFAULT = "tiiuae/falcon-7b-instruct"

    def __init__(self, model_name: str = "tiiuae/falcon-7b-instruct", **kwargs) -> None:
        super().__init__(model_name, **kwargs)


class CFG_GPT4AllJ(CFGWrapper):
    """GPT4All-J v1.3-jazzy for the negative-prompting chatbot study (Section 3.4)."""

    def __init__(self, model_name: str = "nomic-ai/gpt4all-j", **kwargs) -> None:
        kwargs.setdefault("guidance_strength", 3.0)
        super().__init__(model_name, **kwargs)

    @torch.no_grad()
    def generate_with_negative_prompt(
        self,
        positive_system_prompt: str,
        negative_system_prompt: str,
        user_prompt: str,
        max_new_tokens: int = 256,
        guidance_strength: Optional[float] = None,
        temperature: float = 0.9,
        top_p: float = 0.95,
        do_sample: bool = True,
    ) -> str:
        """Equation 5 negative prompting (Section 3.4).

        ``log \\hat P(w|c,\\bar c) = log P(w|\\bar c) +
        gamma (log P(w|c) - log P(w|\\bar c))`` where ``c`` is the edited
        system prompt and ``\\bar c`` the default system prompt. Both passes
        share the same continuation; the unconditional-style drop used in
        basic prompting is replaced here by the negative conditioning.
        """
        gamma = self.guidance_strength if guidance_strength is None else float(guidance_strength)
        pos_ctx = positive_system_prompt + "\n\n" + user_prompt
        neg_ctx = negative_system_prompt + "\n\n" + user_prompt
        pos_ids = self.tokenizer(pos_ctx, return_tensors="pt").input_ids[0].tolist()
        neg_ids = self.tokenizer(neg_ctx, return_tensors="pt").input_ids[0].tolist()
        generated: List[int] = []
        for _ in range(max_new_tokens):
            pos_lp = self._next_token_logits(pos_ids + generated)
            neg_lp = self._next_token_logits(neg_ids + generated)
            guided = negative_cfg_logits(pos_lp, neg_lp, gamma)
            if do_sample:
                probs = F.softmax(guided / max(temperature, 1e-8), dim=-1)
                probs = _top_p_mask(probs, top_p)
                next_id = int(torch.multinomial(probs, num_samples=1).item())
            else:
                next_id = int(torch.argmax(guided, dim=-1).item())
            if next_id == self.tokenizer.eos_token_id:
                break
            generated.append(next_id)
        return self.tokenizer.decode(generated, skip_special_tokens=True)


MODEL_REGISTRY: Dict[str, Tuple[str, CFGWrapper]] = {
    "gpt2": (CFG_GPT2.DEFAULT, CFG_GPT2),
    "pythia": ("EleutherAI/pythia-410m", CFG_Pythia),
    "llama": (CFG_LLaMA.DEFAULT, CFG_LLaMA),
    "guanaco-65b": ("TheBloke/guanaco-65B-GPT4True", CFG_Guanaco65B),
    "wizardlm-30b": ("WizardLM/WizardLM-30B-V1.0", CFG_WizardLM30B),
    "codegen-350m-mono": ("Salesforce/codegen-350M-mono", CFG_CodeGen),
    "codegen-2b-mono": ("Salesforce/codegen-2B-mono", CFG_CodeGen),
    "codegen-6b-mono": ("Salesforce/codegen-6B-mono", CFG_CodeGen),
    "falcon-7b": ("tiiuae/falcon-7b", CFG_Falcon7bBase),
    "falcon-7b-instruct": ("tiiuae/falcon-7b-instruct", CFG_Falcon7bInstruct),
    "gpt4all-j": ("nomic-ai/gpt4all-j", CFG_GPT4AllJ),
}
