# Projection Workbench → Google Sheet sync (one-time setup)

The local workbench cannot use ChatGPT's Google Drive connector directly. This bridge gives the local app a narrow authenticated write path to the existing **Fantasy Projection Tracker** without giving it general Google Drive credentials.

## 1. Install the Apps Script bridge
1. Open **Fantasy Projection Tracker** in Google Sheets.
2. Choose **Extensions → Apps Script**.
3. Replace the editor contents with `projection_sheet_bridge.gs` from this repo.
4. At the top of the script, replace `REPLACE_WITH_A_LONG_RANDOM_TOKEN` with a long random secret you choose. Do not commit that secret back to GitHub.
5. Save the script.

## 2. Deploy it as a Web App
1. In Apps Script choose **Deploy → New deployment**.
2. Select **Web app**.
3. Execute as: **Me**.
4. Who has access: **Anyone**. The shared token is required for every write; the bridge exposes no spreadsheet read endpoint.
5. Deploy and copy the resulting URL ending in `/exec`.

## 3. Configure the local workbench
Double-click **Configure Projection Sheet Sync.command** and paste:
- the `/exec` URL
- the same shared token used in Apps Script

The config is stored locally in `~/.fantasy_decision_lab/projection_sheet_sync.json` with restricted file permissions.

## Upsert behavior
- Canonical key: `season + week + scoring profile + normalized player`.
- A new player/week/league creates one tracker row.
- A later revision for that same player/week/league updates the existing row instead of creating a duplicate.
- The local `projections.json` still preserves every revision for audit/history.
- Postgame rows with an existing provider Actual FP are protected from accidental projection overwrites.
- Actual/diagnostic columns are preserved when a pregame projection is revised.
- If Sheet sync is not configured or is temporarily unavailable, the workbench queues the write locally and retries queued writes on a later live launch.

## QA safety
The QA workbench uses `projections_qa.json`, does not call the paid AI/search path, and never syncs fixture projections to Google Sheets.
