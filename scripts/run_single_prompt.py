import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sync_prompts
from forecaster.agents.question_definition import QuestionDefinitionAgent
from forecaster.db import db_cursor, insert_forecast_question
from forecaster.pipeline import ForecastPipeline

parser = argparse.ArgumentParser()
parser.add_argument("symbol")
parser.add_argument("forecast_id", type=int)
args = parser.parse_args()

SYMBOL = args.symbol
FORECAST_ID = args.forecast_id

# get_active_prompt() reads prompt_text from prompt_registry, not from
# personas/*.md directly -- editing the persona file alone has no effect
# until something reseeds the DB row. run_pipeline.ps1 normally does this via
# sync_prompts.py before every real pipeline run; this script bypasses that
# entry point, so it has to call sync itself to test the latest persona edits
# rather than silently running whatever prompt was already active in the DB.
print("Syncing prompt_registry from personas/*.md ...")
synced = sync_prompts.sync()
print("No prompt changes to sync." if synced == 0 else f"Reseeded {synced} agent(s).")

pipeline = ForecastPipeline()

# Show + clear whatever's currently there first, so it's obvious afterward
# whether the new prompt actually produced different questions or just
# regenerated the same ones.
with db_cursor() as cur:
    cur.execute(
        "SELECT question_text FROM forecast_questions WHERE forecast_id = %s ORDER BY id",
        (FORECAST_ID,),
    )
    old_questions = [row[0] for row in cur.fetchall()]
    print(f"--- {len(old_questions)} existing questions for forecast_id={FORECAST_ID} (before) ---")
    for q in old_questions:
        print(f"  - {q}")

    cur.execute("DELETE FROM forecast_questions WHERE forecast_id = %s", (FORECAST_ID,))
    print(f"Deleted {cur.rowcount} rows")

position = pipeline._get_position_context(SYMBOL)
result = QuestionDefinitionAgent().run(symbol=SYMBOL, position=position, forecast_id=FORECAST_ID)

# QuestionDefinitionAgent.run() only writes forecasts.question_def_output -- it
# never inserts forecast_questions rows (that's pipeline orchestration, not
# agent behavior). Replicate ForecastPipeline._stage_a's insert loop here so
# forecast_questions actually reflects the new decomposition.
questions = result.output.get("questions") or []
for question in questions:
    question["id"] = insert_forecast_question(
        FORECAST_ID, **pipeline._question_insert_kwargs(question)
    )

print(f"\n--- {len(questions)} new questions for forecast_id={FORECAST_ID} (after) ---")
for q in questions:
    print(f"  - {q.get('question_text')}")