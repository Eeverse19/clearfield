# Demo script

Target: a tight, rehearsed demo. Every query and response below is pre-cached under `demo/cached-responses/` — the demo must survive an API outage. A backup video of the full run is recorded before submission day.

## Moment 0 — Human opening (~30 sec)

A farmer deciding whether to plow a field; a kid walking to school. One sentence: "ClearField answers where to go first." No architecture, no logos, no setup.

## Moment 1 — Country switch (~30 sec)

Laos ranked map on screen. One click on the country selector → Cambodia ranked map, same UI, same legend, same score components. Line: "Same code, same schema, same math — only the profile changed." This is the portability proof; do not explain it, show it.

## Moment 2 — "Why is this zone ranked #3?" (~60 sec)

Click a top zone. Ask in Lao, then in Khmer: why is this zone ranked #3? Spark answers from the zone's stored score components — strike density, crater evidence, exposure, surveyed status — with the actual numbers on screen. Then generate the survey report from the zone's facts (template + facts, no free text). If the live API is slow, play the cached response; never wait on camera.

## Moment 3 — Offline triage (~60 sec)

Wi-Fi visibly off (airplane mode on screen). Photo of a find + GPS + Lao notes → Glimmer produces a structured record → connectivity restored → record syncs via `POST /finds` → re-scoring is run explicitly (`pipelines/scoring.py`; a find never silently re-ranks) → the zone's score updates on the map. If the local model is below the pass bar, use the pre-recorded clip and say so in the submission — never fake a live run.

## Moment 4 — The differentiator (~30 sec, stretch)

The dud-field layer: per-zone live-ordnance probability from strike weapon mix × crater morphology × published dud rates, with uncertainty shown and a method note on screen. Line: "We don't just map craters. We estimate what's still live in the ground." Cut this moment first if it is not ready — a missing moment beats a broken one.

## Close (~30 sec)

"One pipeline, any bombed country — clearance money goes where it saves the most lives per dollar." End on the map, not on a slide.

## Rules

- Never claim the system clears mines. It prioritizes; humans clear.
- Never show synthetic imagery or generated craters as real data. Anything illustrative is labeled.
- Never let a live API call block the demo. Cached responses exist for every scripted step.
- If anything fails live, say so and cut to the backup video. A graceful cut beats a frozen screen.
