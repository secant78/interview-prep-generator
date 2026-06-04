"""
Cost tracking for Gemini API calls.
Accumulates token usage across multiple calls and calculates total cost.
"""

# Pricing per 1M tokens (USD) — as of June 2026
PRICING = {
    "gemini-2.5-flash": {
        "input":  0.15,
        "output": 0.60,
    },
    "gemini-2.5-pro": {
        "input":  1.25,
        "output": 10.00,
    },
    "gemini-2.0-flash": {
        "input":  0.10,
        "output": 0.40,
    },
    "gemini-2.0-flash-lite": {
        "input":  0.075,
        "output": 0.30,
    },
}

DEFAULT_PRICING = {"input": 0.15, "output": 0.60}  # fallback to 2.5 flash rates


class CostTracker:
    def __init__(self, model: str):
        self.model    = model
        self.input_tokens  = 0
        self.output_tokens = 0
        self.calls    = []  # list of (label, input_tokens, output_tokens)

    def add(self, label: str, response):
        """Record token usage from a Gemini response object."""
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return
        inp = getattr(usage, "prompt_token_count", 0) or 0
        out = getattr(usage, "candidates_token_count", 0) or 0
        self.input_tokens  += inp
        self.output_tokens += out
        self.calls.append((label, inp, out))

    def add_image_tokens(self, label: str, n_frames: int, tokens_per_frame: int = 258):
        """Manually record image token cost (frames sent as inline images)."""
        inp = n_frames * tokens_per_frame
        self.input_tokens += inp
        self.calls.append((label, inp, 0))

    @property
    def pricing(self) -> dict:
        # Match on prefix in case model has version suffix
        for key, rates in PRICING.items():
            if self.model.startswith(key):
                return rates
        return DEFAULT_PRICING

    @property
    def total_cost(self) -> float:
        rates = self.pricing
        return (
            self.input_tokens  / 1_000_000 * rates["input"] +
            self.output_tokens / 1_000_000 * rates["output"]
        )

    def summary(self) -> str:
        """Return a human-readable cost summary string."""
        rates = self.pricing
        input_cost  = self.input_tokens  / 1_000_000 * rates["input"]
        output_cost = self.output_tokens / 1_000_000 * rates["output"]
        lines = [
            f"**API Cost Summary** — `{self.model}`",
            f"| Call | Input tokens | Output tokens |",
            f"|------|-------------|---------------|",
        ]
        for label, inp, out in self.calls:
            lines.append(f"| {label} | {inp:,} | {out:,} |")
        lines += [
            f"| **Total** | **{self.input_tokens:,}** | **{self.output_tokens:,}** |",
            f"",
            f"Input cost:  ${input_cost:.4f}  ({self.input_tokens:,} tokens × ${rates['input']}/1M)",
            f"Output cost: ${output_cost:.4f}  ({self.output_tokens:,} tokens × ${rates['output']}/1M)",
            f"**Total: ${self.total_cost:.4f}**",
        ]
        return "\n".join(lines)
