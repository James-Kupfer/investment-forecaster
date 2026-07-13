from typing import Optional


class TriageAgent:
    """No LLM call — pure threshold gate on the magnitude of the prior
    adjusted_score. Replaces the v1 compound_conviction gate, retired
    alongside the single-question model (see
    C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md).
    Magnitude, not sign, is what matters here: a strong prior sell signal is
    just as worth re-forecasting as a strong prior buy signal — it's a near-zero
    prior score (unclear/insufficient signal last time) that this gate skips."""

    THRESHOLD = 0.30

    def run(self, prior_adjusted_score: Optional[float]) -> bool:
        """Return True if position should proceed through the pipeline."""
        if prior_adjusted_score is None:
            return True  # first run always passes
        return abs(prior_adjusted_score) >= self.THRESHOLD
