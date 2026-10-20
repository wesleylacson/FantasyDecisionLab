# Fantasy Projection Model — Historical README Snapshot

Source: the `README` tab in the Fantasy Projection Tracker, reconciled 2026-10-20. This is durable model context; current injuries, roles, matchup, market and weather must still be refreshed for each projection.

## Core purpose and audit rules
- Preserve the pregame forecast as the benchmark; never replace a projection with an actual.
- Add provider-scored actual fantasy points after the game and diagnose the miss by volume, efficiency, TD variance, negative plays, injury/game script and supporting cast.
- Use Flaim/ESPN/Sleeper provider totals as authoritative actual FP. Component stat lines are diagnostic evidence, not a substitute for provider scoring.
- Accuracy comparisons use played-game rows with both pregame forecasts and provider actuals. Exclude DNP/IR and missing model projections.
- Blank means unknown/unavailable, not zero. Do not fabricate missing historical components. Drake Maye Week 1 model projection is permanently missing. Malik Nabers Week 5 had a final FP-only weather revision; unrecovered components remain blank.

## General projection construction
1. Project the team opportunity pool / game environment.
2. Estimate the player's current role/share and scenario splits.
3. Project component efficiency, touchdowns, first downs and negative plays separately.
4. Apply adjusted matchup/scheme evidence and an external market/consensus check.
5. Apply league scoring and an uncertainty range.
6. Lock the pregame assumptions and app benchmark before kickoff; diagnose after actuals.

Short samples should normally shrink toward stable season/current-staff baselines. A genuinely concentrated current-staff contingency role can override a season average when evidence is strong. One explosive play, one high-attempt game or a short TD streak is not automatically a new baseline.

## Running backs
- Separate carries/targets from yards per carry and TD expectation.
- Evaluate carry competition, passing-down role, goal-line role, OL/run blocking and yards before contact, run concepts versus defensive fronts, stacked-box tendencies and game script.
- Backup efficiency does not automatically scale to starter volume.
- Model team TD environment and goal-line share separately from raw workload.
- Recent concentrated snap/rush/route shares can justify a role change, but re-check the injured/absent teammate before carrying it forward.

## Wide receivers and tight ends
- Project team dropbacks and the positional passing pie before individual target share.
- Split target value conceptually into short/intermediate/deep usage; weather, QB style, pressure and scheme can change depth/efficiency without changing target concentration.
- Formal matchup check: role/alignment and route families versus man/zone and relevant shells; likely CB/nickel/safety deployment and verified shadow tendencies; QB-pressure/weather interaction; opponent-adjusted comparisons to similar roles and offensive environments.
- Do not infer shadow coverage from depth charts alone and do not equate two-high with Cover 2.
- Map the matchup once into targets, catch rate, yards, TD and first-down assumptions; avoid stacking correlated adjustments.
- Alpha-WR weather rule from Week 5: downgrade efficiency/ADOT/catch/TD expectation before target share. Weather alone should not heavily suppress elite target concentration.
- Replacement-QB rule: cap schematic matchup boosts when QB/offense quality may prevent exploitable coverage from becoming usable volume.

## Quarterbacks
- Project team dropbacks/pass attempts first.
- Pressure-adjust YPA, passing TD rate, sacks/turnovers and scramble/rushing opportunity separately.
- A broad 'tough defense' label should not depress every component without a mechanism.
- Mobile-QB injuries should use scenario branches rather than a flat rushing haircut. After full-go clearance, preserve demonstrated scramble behavior unless there is evidence of designed restriction; pressure can create scramble value as well as sacks/efficiency loss.
- Explicitly price high-attempt and low-attempt game-script tails instead of compressing everything into one script.

## Matchup, weather and uncertainty
- Use adjusted positional matchup data as a second check on raw points allowed and test concept fit.
- Treat blowout, injury and weather as scenario probabilities/range-width inputs. Separate in-game shocks from pregame model misses.
- Weather is a cross-cutting modifier to component assumptions, not a blunt post-hoc fantasy-point adjustment.
- Report a central/median expectation separately from ceiling/range when useful.

## Market benchmark
The app projection is a required benchmark and useful prior, not the answer. A material disagreement should be traceable to explicit component assumptions. Track model MAE versus app MAE over time rather than assuming the custom model is better.

## Week 5 carry-forward examples
- Braelon Allen: 86% snaps, 80% rush share, 80% route share and 14% target share supported an all-down contingency-role prior while Hall was out; re-check Hall status before projecting.
- Malik Nabers: elite target concentration remains meaningful even when weather changes efficiency; do not let a Burden-tier alternative beat him on a narrow projection gap absent a material role/injury reason.
- Luther Burden: manufactured touches and a good schematic matchup do not guarantee dominant target share; QB/offense quality can cap the payoff.
- Rhamondre Stevenson: do not materially raise or lower his baseline solely from a short scoring streak; explicitly model teammate workload uncertainty.
- Trevor Lawrence: do not raise the baseline solely because of one 39-attempt game.

## Historical tracker provenance
The tracker contains original pregame component lines, app totals, provider actuals, diagnostics and selected app component snapshots. Historical values should migrate into the new workbench without recomputing them from today's formulas. Where a projection was revised more than once in a week, the workbench keeps local revision history, while the canonical tracker row represents the latest/official weekly projection.
