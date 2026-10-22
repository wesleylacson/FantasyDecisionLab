# Fantasy Decision Lab

Local fantasy-football decision tool for Start/Sit analysis and weekly projection building.

## First run on Mac

1. Keep this folder somewhere permanent (for example `~/Applications/FantasyDecisionLab` or `~/Documents/FantasyDecisionLab`).
2. Double-click **First-time Setup.command**.
3. Paste your FantasyPros API key when prompted. The key is stored locally in `~/.fantasy_decision_lab/config.json` with user-only file permissions.
4. Double-click **Launch Fantasy Decision Lab.command** whenever you want to use the Start/Sit app.

Your existing FantasyPros accuracy CSVs should remain somewhere under `~/Downloads` with their existing names.

## Projection Workbench pilot

Double-click **Launch Projection Workbench.command** to open the standalone projection MVP at `http://127.0.0.1:8766`.

The pilot supports:
- player/week/scoring-specific projection records
- editable projected stat lines and automatic fantasy-point calculation
- the four projection pillars with separate system evidence and user-context notes
- category-based evidence coverage rather than reliance on one source
- append-only projection revisions and one locked official pregame projection
- actual-result grading with our absolute error versus app absolute error
- a cumulative MAE-vs-app line chart filterable by position

Projection records are stored locally in `~/.fantasy_decision_lab/projections.json`. The pilot is intentionally standalone so it can be tested without destabilizing the existing Start/Sit app; once the workflow is validated it can be mounted into the main app navigation.

## Headless postmortem learning

Postgame learning is intentionally **not** an interactive Workbench button. A scheduled Tuesday process reads the synced Fantasy Projection Tracker after actuals are available, updates source-specific postmortem observations, generates diagnoses, links evidence to existing lessons, and queues genuinely new/refined lessons for human review.

Key files:
- `projection_postmortem_ai.py` — structured diagnostic/candidate-generation contract for local or future service execution
- `POSTMORTEM_OBSERVATION_SCHEMA.md` — normalized component-observation schema and historical backfill policy
- `POSTMORTEM_LEARNING_PIPELINE.md` — scheduled workflow, idempotency, review gate, and promotion rules

The Google Sheet contains the corresponding `Postmortem Observations`, `Postmortem Diagnostics`, `Learning Registry`, `Learning Evidence Map`, `Candidate Learning Queue`, and `Postmortem Runs` tables. Candidate generation is automatic; promotion into active model knowledge remains human-gated.

## Updating

After this folder is cloned from the GitHub repository, double-click **Update Fantasy Decision Lab.command**. It runs `git pull --ff-only` and refreshes Python dependencies.

## Data

The Start/Sit app keeps FantasyPros comparison caches under `~/Downloads/fantasy_decision_lab_cache/`. The in-app refresh buttons can invalidate matchup, position or all cached ballots.

The Projection Workbench keeps its revision history and grading data under `~/.fantasy_decision_lab/projections.json`.

## Security

Do not commit API keys. The repository `.gitignore` excludes the local virtual environment, logs and other machine-specific files. The FantasyPros key lives outside the repository.
