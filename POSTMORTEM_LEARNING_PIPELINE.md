# Scheduled Postmortem Learning Pipeline

## Purpose

The Workbench should not require an interactive **Analyze Projection** button. Projection generation remains interactive; postgame diagnosis and candidate-learning generation run headlessly on a schedule.

The learning pipeline is intentionally separated into observation, diagnosis, candidate generation, and human-gated promotion.

## Data flow

1. `Projection Tracker` stores the canonical player/week projection and actual.
2. `Postmortem Observations` stores immutable source-specific component projections and postgame deltas.
3. `Postmortem Diagnostics` stores one source-specific diagnosis per projection.
4. `Learning Evidence Map` links observations to existing lessons as `support`, `contradict`, `context`, or `exclusion`.
5. `Candidate Learning Queue` stores only proposed `new`, `refine`, or `merge` lessons. New rows begin as `Pending`.
6. `Postmortem Runs` provides the idempotency/run log so a completed week is not analyzed repeatedly.
7. `Learning Registry` contains reviewed lessons. Only reviewed/promoted lessons are eligible to influence future projections.

## Headless AI module

`projection_postmortem_ai.py` defines the same contract for local/CLI use and future service execution.

Default configuration:

- model: `FANTASY_POSTMORTEM_MODEL`, default `gpt-6-luna`
- reasoning: `FANTASY_POSTMORTEM_REASONING`, default `medium`
- web search: enabled at medium context only when a causal question requires fresh role/injury/scheme evidence

The module returns structured diagnoses and candidate lessons. It never mutates active knowledge and every candidate is marked `Pending` with `human_review_required=true`.

## Scheduled ChatGPT job

The cloud-scheduled Tuesday postmortem is the primary unattended runner. It should:

1. check `Postmortem Runs` and skip the week if a `complete` run already exists;
2. verify newly completed projections have actuals and source-specific observations;
3. populate missing descriptive observation deltas before reasoning;
4. read the active `Learning Registry` and existing `Learning Evidence Map`;
5. diagnose each Workbench/Chat projection source independently;
6. write `Postmortem Diagnostics` rows;
7. add only justified evidence links to existing lessons;
8. write genuinely new/refine/merge proposals to `Candidate Learning Queue` as `Pending`;
9. write a `complete` row to `Postmortem Runs` even when zero new candidates are proposed;
10. proactively send a concise review packet to the user with approve / merge-modify / reject recommendations.

## Idempotency

The run key is `season|week|postmortem`. A completed run prevents duplicate analysis. A rerun is allowed only when the previous run is explicitly marked `partial` or `failed`, or when the human requests a rerun because materially new data became available.

Candidate IDs are deterministic from week + candidate type + scope + subject + statement. This reduces duplicate proposals across retries.

## Promotion gate

Candidate generation is automatic. Promotion is not.

A human review must choose one of:

- `Promoted` — create or update the reviewed lesson;
- `Merged` — fold the useful content into an existing lesson;
- `Rejected` — preserve the rejection so the same weak candidate is less likely to recur.

Promotion should update the Sheet `Learning Registry` and the app-consumed knowledge source (`projection_knowledge_seed.json` or a future registry-sync path). Pending or rejected candidates must never enter `relevant_knowledge()`.

## Statistical guardrails

- Do not promote a rule merely because fantasy points missed.
- Diagnose opportunity, conversion, production, scoring variance, first downs, and total separately.
- Do not learn from isolated realized touchdowns.
- Treat unforeseeable DNP/in-game injury outcomes as exclusions/context.
- Prefer reinforcing or bounding an existing rule over creating a new one.
- Preserve contradictory evidence.
- `no new lesson` is a valid and desirable result.
- A single game should rarely create a High-confidence methodology rule unless it directly reveals a stable role/personnel change.

## Long-term goal

Track candidate-review quality itself: acceptance rate, unchanged-promotion rate, merge/refinement rate, rejection rate, and recurrence of rejected ideas. Auto-promotion should only be considered after the review history demonstrates strong precision in a narrow, well-defined class of lessons.
