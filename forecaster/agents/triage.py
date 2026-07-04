from typing import Optional


class TriageAgent:
    """No LLM call — pure threshold gate on prior compound conviction."""

    THRESHOLD = 0.30

    def run(self, prior_compound_conviction: Optional[float]) -> bool:
        """Return True if position should proceed through the pipeline."""
        if prior_compound_conviction is None:
            return True  # first run always passes
        return prior_compound_conviction >= self.THRESHOLD
