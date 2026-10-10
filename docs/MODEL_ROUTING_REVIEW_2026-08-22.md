# Model Routing & Caching — Investment Forecaster

**Date:** 2026-08-22. Prices checked against each provider's pricing page on this date. All token
counts come from `docs/cost_report.csv` — 51 real forecasts across 13 symbols, 2026-07-12 to 07-18.

Sections 1 and 2 are applied. Sections 3 and 4 are proposals.

---

## 1. Model assignments — applied

| Agent | Model | Changed |
|---|---|---|
| `question_definition` | `claude-opus-5` | |
| `elicitation` | `claude-opus-5` | |
| `aggregation` | `claude-opus-5` | |
| `risk_judge` | `claude-sonnet-5` | |
| `earnings` | `claude-sonnet-5` | |
| `primary_source` | `claude-sonnet-5` | |
| `review` | `claude-sonnet-5` | |
| `macroq` | `claude-sonnet-5` | ✔ was Haiku |
| `confidence_judge` | `claude-sonnet-5` | ✔ was Haiku |
| `tech_judge`, `momentum`, `trend`, `volume` | `claude-haiku-4-5` | |

Cost goes from $1.39 to $1.44 per forecast, up 4%.

There is no meaningful cost saving available here. The four agents that account for 80% of spend
are already on the right models. These two changes buy accuracy, not savings.

**The rule going forward: Haiku only for the four technical agents. Anything that makes a judgement
runs on Sonnet 5 or Opus 5.**

That rule is about capability, not price. `BaseAgent.call()` never sets a `thinking` parameter.
Sonnet 5 and Opus 5 reason anyway — their thinking is on by default. Haiku 4.5 only reasons when
you explicitly ask it to, which this code never does. So a Haiku agent is producing answers with no
reasoning behind them at all. That is fine for reading an RSI value off a chart. It is not fine for
setting a probability.

`confidence_judge` sets the final calibrated probability for every sub-question — the number you
Brier-score later. `macroq` builds the macro read that every sub-question then depends on, so a bad
call there affects all of them, not one. Those were the two worth moving.

## 2. Token budgets — replaced with one ceiling, applied

Every per-agent `max_tokens` is gone. `BaseAgent` now has a single constant,
`DEFAULT_MAX_TOKENS = 50_000`, and no agent overrides it.

**Why one number instead of twelve tuned ones:**

- `max_tokens` is a ceiling, not a reservation. You pay for tokens the model actually writes, so a
  higher ceiling costs nothing until something uses it.
- Adaptive thinking does not spend more just because the ceiling is higher. Claude decides how much
  to think from task complexity and the `effort` setting, not from the size of `max_tokens`.
  (Anthropic's extended-thinking docs are explicit on this.) That was the only real argument for
  keeping the caps tight, and it does not hold.
- 50,000 fits under every model in use: Opus 5 and Sonnet 5 allow 128,000 output tokens, Haiku 4.5
  allows 64,000.
- The highest output ever recorded in this pipeline is 9,590 tokens. 50,000 is more than five times
  that.

**What tight caps were actually buying: silent truncation.** Three agents have been cut off mid-run
— `risk_judge`, `aggregation`, and `primary_source`. Truncation returns HTTP 200 with a
complete-looking response, so it does not announce itself. `BaseAgent` now flags
`stop_reason == 'max_tokens'`, but detecting a lost run is not the same as not losing it.

Tuning twelve numbers against 51 runs was the wrong approach — especially with only 16 to 21 runs
per Sonnet agent, and with `primary_source`'s recorded "maximum" of 8,000 being nothing more than
where its cap stopped it. The right move is to make the number large enough that it stops mattering.

The one thing a tight cap did provide was a runaway-cost guard. At Opus 5 output prices, a single
call that ran to 50,000 tokens would cost $1.25 instead of the $0.05 an `elicitation` call costs
today. Nothing in 522 logged calls has come within 5x of the new ceiling, and truncation has
actually happened three times, so the trade is clearly worth taking — but if a run ever comes back
surprisingly expensive, this is the first place to look.

Roughly 40 lines of comments justifying the old per-agent numbers were removed along with them.

## 3. Caching — worth doing, but only for the right calls

Not built yet. `tokens_cached` is 0 across all 522 rows, `cache_control` appears nowhere, and
`BaseAgent.call()` sends the system prompt as a plain string.

### Why it can't just be switched on globally

Caching a prompt costs extra the first time. Anthropic charges 1.25x the normal input price to
write a 5-minute cache, or 2x for a 1-hour cache. After that, every reuse costs 10% of normal.

So caching only pays if the same prompt gets sent more than once. Send it once and you have just
paid a 25% surcharge for nothing.

The exact break-even, for a prompt of P tokens sent n times:

```
no caching   = n × P
5-minute     = P × (1.25 + 0.1 × (n − 1))    pays from n = 1.28, so from the 2nd send
1-hour       = P × (2.00 + 0.1 × (n − 1))    pays from n = 2.11, so from the 3rd send
```

### Which agents qualify

**Always cache: `elicitation`, `review`, `confidence_judge`.** These run once per sub-question,
averaging 3.4 times per forecast. The same persona goes out 3.4 times inside a single forecast, so
they clear the 5-minute break-even even when you are running one symbol on its own. Use the
5-minute cache.

**Cache when the batch has 3 or more symbols: `question_definition`, `aggregation`, `risk_judge`,
`earnings`, `primary_source`, `macroq`.** These run once per symbol. One symbol means one send,
which loses money. Two symbols with a 1-hour cache breaks exactly even — no gain. Three or more
starts paying. Use the 1-hour cache.

**Never cache: `tech_judge`, `momentum`, `trend`, `volume`.** Their personas are 1,280–2,431 tokens.
Haiku won't cache anything under 4,096 tokens, so the option doesn't exist.

### What it's worth

| Run | Saving |
|---|---|
| One symbol on its own | **$0.053 per forecast**, about 4% |
| Batch of 5 | $0.053 per forecast, plus $0.059 per symbol from the once-per-symbol agents |
| Batch of 15 | $0.053 per forecast, plus $0.088 per symbol — roughly **$2.10 on a $21.60 batch** |

For contrast: caching `question_definition` on a single-symbol run would **cost** an extra $0.016.
Its persona is about 12,700 tokens on Opus 5, written once and never reused. The rule above skips it.

### How to build it

Add an optional `cache_system: bool = False` to `BaseAgent.call()`. When true, it attaches a
`cache_control` breakpoint to the system prompt. Let the pipeline decide, so no agent hardcodes it:

```python
cache_system = (expected_calls_sharing_prefix >= 2)
```

The pipeline already knows both numbers — how many sub-questions survived triage (that's the
fan-out agents) and how many symbols are in the batch (that's everything else).

**One trap worth knowing about.** Stage C runs its sub-question forecasts in parallel through a
`ThreadPoolExecutor`. If all 3–4 calls start at the same moment, none of them has written the cache
yet, so all of them pay the write price. You get 4 writes instead of 1 write and 3 cheap reads —
turning the best saving in the pipeline into a 25% surcharge.

The fix: send the first sub-question's call on its own, wait for it to come back, then submit the
rest to the pool. It costs one call's latency per stage.

Also start checking `tokens_cached` after a run. It is 0 today, so any non-zero number confirms the
flag is actually reaching the API.

## 4. Should the pipeline change its running order? Almost certainly not

Today the pipeline finishes one symbol at a time: symbol 1 runs Stages A through D, then symbol 2
starts. The alternative would be running every symbol through Stage A, then every symbol through
Stage B agent by agent, and so on.

The alternative looks better for caching, because each agent's prompt would be sent back to back
across all symbols instead of being separated by a full symbol's run.

**It is almost certainly unnecessary, because reusing a cache resets its expiry timer.** In the
current order, each agent is used once per symbol, and each use restarts that agent's clock. The
cache survives the whole batch as long as the next symbol reaches that agent before the timer runs
out.

So the whole decision comes down to one number: **how long does one symbol take to run?** You
already log it, in `llm_call_log.duration_ms`:

```sql
SELECT forecast_id,
       SUM(duration_ms) / 1000.0  AS symbol_seconds,
       MAX(duration_ms) / 1000.0  AS slowest_call_seconds
FROM   llm_call_log
GROUP  BY forecast_id
ORDER  BY symbol_seconds DESC
LIMIT  20;
```

| One symbol takes | What to do |
|---|---|
| Under 5 minutes | Use the 5-minute cache everywhere. It never expires, because the next symbol always arrives first. Don't change the order. |
| 5 to 60 minutes | The 5-minute cache dies between symbols. Use the 1-hour cache for the once-per-symbol agents instead. Don't change the order. |
| Over 60 minutes | Even the 1-hour cache dies between symbols. Reordering is the only way to get cross-symbol savings. |

### What reordering would cost

Three things work today because the pipeline finishes one symbol before starting the next:

1. **A failed symbol doesn't take the batch down.** Reordering puts every symbol in flight at once,
   so failure handling has to be rebuilt.
2. **Finished forecasts appear as the batch runs.** Reordering means nothing is finished until
   everything is finished.
3. **Each symbol saves to the database at each stage boundary.** Reordering means holding every
   symbol's partial results in memory until the end.

That is a real refactor, and it buys about 5% of batch cost.

**Recommendation:** build §3, run the query above, and only revisit this if a single symbol takes
over an hour. If it does, reorder Stage B by itself rather than the whole pipeline — its eight
symbol-level agents are independent of each other and carry the least state between stages.
