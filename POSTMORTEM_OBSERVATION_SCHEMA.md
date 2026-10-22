# Postmortem Observation Schema

## Purpose

This layer records what a projection got right or wrong before the system tries to explain why.

The Projection Tracker remains the canonical player/week record. `Postmortem Observations` is a normalized child table with one row per:

`projection_key + projection_source + component`

This avoids widening the main tracker indefinitely and lets Workbench, Chat, and future projection sources be graded against the same game outcome.

## Design principle

Keep observation separate from diagnosis and learning.

1. **Observation** — immutable projected value, actual value, delta, derived rate.
2. **Diagnosis** — later classification such as volume miss, efficiency miss, game-script miss, role change, or variance.
3. **Candidate learning** — a proposed reusable rule supported by one or more diagnoses.
4. **Promotion** — a later gate that decides whether a candidate learning becomes persistent model knowledge.

Do not allow an outcome by itself to create a learning rule.

## Columns

| Column | Meaning |
| --- | --- |
| Observation Key | Stable key: `projection_key|source|component` |
| Projection Key | Canonical player/week/league key from Projection Tracker |
| Week | NFL week |
| League | Scoring environment |
| Player | Player display name |
| Position | QB/RB/WR/TE |
| Opponent | Opponent |
| Source | Workbench, Chat, App, or future source |
| Model / Version | Model/reasoning configuration or source version |
| Component | Atomic stat or derived rate |
| Stage | Descriptive stage in the projection chain |
| Projected | Pregame projected value |
| Actual | Observed result after game |
| Delta | `actual - projected` |
| Abs Error | `abs(delta)` |
| Relative Error | `delta / abs(projected)` when meaningful |
| Direction | `hit`, `overprojected`, or `underprojected` |
| Severity | Reserved for later versioned thresholds; blank until thresholds are defined |

## Initial component vocabulary

### Opportunity
- pass_attempts
- rush_attempts
- targets

### Conversion
- receptions
- catch_rate

### Production
- pass_yards
- rush_yards
- rec_yards
- pass_yards_per_attempt
- yards_per_carry
- yards_per_target
- yards_per_reception

### Scoring variance
- pass_tds
- rush_tds
- rec_tds

TD projections are expectations, not deterministic event forecasts. A realized TD difference should be preserved but should not automatically be treated as a model failure.

### Negative play
- interceptions

### First downs
- first_downs

### Fantasy total
- fantasy_points

## Derived-rate formulas

When the required denominator is available and non-zero:

- `catch_rate = receptions / targets`
- `yards_per_target = rec_yards / targets`
- `yards_per_reception = rec_yards / receptions`
- `yards_per_carry = rush_yards / rush_attempts`
- `pass_yards_per_attempt = pass_yards / pass_attempts`

These derived observations are important because they distinguish an opportunity miss from an efficiency miss. Example: if targets hit but receiving yards miss badly, the later diagnosis layer can examine catch rate and yards per target rather than treating the entire statline as one error.

## Historical backfill

Weeks 1–6 were backfilled from the canonical legacy in-chat projections already preserved in Projection Tracker.

Backfill policy:

- Legacy projection source is `Chat`.
- `Model / Version` is `Engine unrecorded`; do not infer a historical engine or reasoning setting.
- Preserve the originally recorded projected component exactly.
- Preserve the originally recorded actual component exactly.
- Never zero-impute a missing historical projected or actual value.
- Derived rates are calculated only when the required numerator and non-zero denominator are both recorded.
- Rows already marked `accuracy_excluded` in the legacy history are not added to the observation corpus.
- Historical rows are descriptive evidence only; they do not automatically create learning rules.

The initial backfill contains 27 usable legacy player/week projections and 302 component/derived observations. Drake Maye Week 1 and Jordan Mason Week 2 remain excluded because their legacy records were already marked accuracy-excluded.

## Week 7 bootstrap

Week 7 Pigskin projections for Rhamondre Stevenson and Luther Burden III are stored from:

- Workbench — GPT-6 Luna, low reasoning
- Chat — GPT-6 Sol, High reasoning

Actual/delta fields remain blank until games are played. The original projections remain immutable.

## Future automation

A postgame process should:

1. ingest actual component stats once;
2. update every observation row sharing that Projection Key;
3. calculate delta / abs error / relative error;
4. assign versioned descriptive miss labels;
5. optionally run a separate diagnostic pass;
6. never promote a diagnostic into persistent knowledge without an explicit evidence gate.

The normalized table should eventually support analysis such as:

- Workbench vs Chat component MAE by position;
- frequency of target hits with receiving-yard misses;
- whether large FP misses are driven by opportunity, conversion, production, or TD variance;
- systematic over/under bias by component;
- candidate learning generation from repeated patterns rather than single-game outcomes.
