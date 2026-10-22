# Projection Workbench test notes

## Week 7 first live test — 2026-10-22

### Rhamondre Stevenson
- Core projection: strong pass.
- Workbench 14.0 vs ESPN 15.29; disagreement shape was coherent rather than arbitrary.
- Workbench modestly increased carries and reduced receptions; overall result stayed within a reasonable central range.
- Historical learning appeared to carry forward appropriately: lead-back role, but not workhorse; lower receiving floor than earlier weeks.
- Matchup/scheme research was too shallow. The prose reached a reasonable conclusion but did not sufficiently investigate Chicago front structure, success rate, yards before contact, explosive-run allowance, RB receiving defense, linebacker coverage, goal-line defense, or OL/DL interaction.
- Expert/market research was too narrow. Preferred analysts (JJ Zachariason, Joel Smyth) should receive extra weight, but their silence must not cause the category to be treated as missing when broader high-quality rankings/projections are available.
- High-depth chat rerun: 11.5 carries, 44 rush yards, 0.42 rush TD, 3.0 targets, 2.4 receptions, 19 receiving yards, 0.04 receiving TD, 3.1 first downs = 14.6 Pigskin FP.
- Chat conclusion: Week 6 was meaningful evidence of a real carry committee, but Stevenson still retains the clearest passing-down / pass-protection role. Chicago's raw fantasy-points-against rank overstates its rushing-efficiency strength; Kiner is the main workload downside.
- First chat-vs-workbench result: 14.6 Chat vs 14.0 Workbench vs 15.29 ESPN. The Workbench number held up well despite weaker explanation/research depth.

### Luther Burden III
- Core projection: interesting but more aggressive / less trustworthy than Stevenson.
- Workbench 18.75 vs ESPN 15.76.
- Biggest model bet is receiving efficiency and TD/first-down expectation, not the extra rushing work.
- 2.5 projected carries is too aggressive as a median and conflicts with the prior tracker lesson to treat gadget carries as ceiling texture rather than reliable weekly volume.
- 7 targets is plausible; the larger concern is converting them into 5.5 catches / 70 yards while route participation remains uncertain.
- Route participation / personnel usage should have been a major downside input. Burden's strong production has at times outpaced route share, and heavy Chicago personnel can remove him from the field.
- Coverage/scheme output improved materially versus Stevenson because it named New England personnel/coverage concepts, but the mechanism still needed cross-checking against actual man/zone usage, slot efficiency allowed, likely Gonzalez assignment, and comparable receivers.
- Expert/market research was clearly broken: ample current analyst rankings existed, yet the pillar said no independent consensus was available.
- Saved summary text said roughly 17 FP while deterministic scoring correctly produced 18.75, suggesting prose generation was not naturally accounting for all PPFD value. Deterministic scoring remains source of truth.

## Product scoreboard after two Workbench runs
- Projection generation / tracker: PASS
- Historical-learning incorporation: PASS / credible
- Statline coherence: PASS
- ESPN comparison capture: PASS
- Sheet connectivity / canonical upsert: PASS
- Matchup headline: PASS
- Matchup deep research: NEEDS MORE DEPTH
- Expert/market research: NEEDS REPAIR
- Deep-dive architecture: TOO SHALLOW; currently expands saved evidence without fresh research
- Cost meter: correct for initial projection call, not yet cumulative across optional deep dives

## Tracker schema decision — Chat vs Workbench
- Keep one canonical row per player / week / league. Do not create duplicate rows for Chat runs.
- Existing `Proj ...` and `Projected FP` fields remain the Workbench projection lane for backward compatibility.
- Append a parallel Chat projection lane to the same row:
  - Chat Proj Pass Att
  - Chat Proj Pass Yds
  - Chat Proj Pass TD
  - Chat Proj INT
  - Chat Proj Rush Att
  - Chat Proj Rush Yds
  - Chat Proj Rush TD
  - Chat Proj Targets
  - Chat Proj Rec
  - Chat Proj Rec Yds
  - Chat Proj Rec TD
  - Chat Proj First Downs
  - Chat Projected FP
  - Chat FP Err
  - Chat Generated At
  - Chat Model/Depth
  - Chat Notes
- `Chat FP Err` is calculated automatically from Actual FP vs Chat Projected FP.
- Reporting goal: compare Workbench MAE vs Chat MAE vs App MAE, including position-level splits and disagreement analysis.
- The same actual result should grade all three pregame benchmarks; no projection source overwrites another.

## Modification targets
1. Deep dives should be allowed a small, targeted second research pass (for example 1-3 focused searches) instead of only rephrasing the original saved source list.
2. Matchup/scheme research should use position-specific diagnostic checklists rather than opponent fantasy rank alone.
3. Market/expert research should follow a hierarchy: preferred analysts -> broader high-quality consensus/rankings -> market projections -> explain agreement/disagreement.
4. Route participation / personnel grouping should be an explicit WR/TE opportunity-risk input.
5. Designed/gadget rushing for WRs should be regressed unless evidence supports a stable weekly role.
6. UI cost should eventually show projection cost, deep-dive cost, and cumulative session cost separately.
7. Performance reporting should add Chat MAE alongside Workbench and App MAE once enough Chat-run samples exist.
