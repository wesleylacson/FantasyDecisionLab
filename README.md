# Fantasy Decision Lab

Local fantasy-football Start/Sit decision tool for QB, RB, WR and TE.

## First run on Mac

1. Keep this folder somewhere permanent (for example `~/Applications/FantasyDecisionLab` or `~/Documents/FantasyDecisionLab`).
2. Double-click **First-time Setup.command**.
3. Paste your FantasyPros API key when prompted. The key is stored locally in `~/.fantasy_decision_lab/config.json` with user-only file permissions.
4. Double-click **Launch Fantasy Decision Lab.command** whenever you want to use the app.

Your existing FantasyPros accuracy CSVs should remain somewhere under `~/Downloads` with their existing names.

## Updating

After this folder is cloned from the GitHub repository, double-click **Update Fantasy Decision Lab.command**. It runs `git pull --ff-only` and refreshes Python dependencies.

## Data

The app keeps FantasyPros comparison caches under `~/Downloads/fantasy_decision_lab_cache/`. The in-app refresh buttons can invalidate matchup, position or all cached ballots.

## Security

Do not commit API keys. The repository `.gitignore` excludes the local virtual environment, logs and other machine-specific files. The FantasyPros key lives outside the repository.
