"""
Daily MacroQ job.

Runs MacroQAgent once and writes the decision tree to macro_state.
Intended to be called by a scheduler (e.g. Windows Task Scheduler) each morning.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forecaster.config import SecretsNotFoundError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from forecaster.agents.macroq import MacroQAgent

    logger.info("Running daily MacroQ job")
    result = MacroQAgent().run()
    root_id = result.output.get("root_macro_state_id")
    if result.error:
        logger.error("MacroQAgent error: %s", result.error)
        sys.exit(1)
    logger.info(
        "MacroQ complete — root macro_state.id=%s cost=$%.6f",
        root_id,
        result.call_cost_usd,
    )


if __name__ == "__main__":
    try:
        main()
    except SecretsNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)
