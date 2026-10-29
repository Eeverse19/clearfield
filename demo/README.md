# demo/ — scripted demo assets

The demo must survive an API outage: every scripted response is
pre-cached under `cached-responses/` (currently only its README —
filling it is TASKS P1-5, after scoring/explain land).

Script: `../docs/demo-script.md`. Rules there are binding, e.g. never
show synthetic imagery as real data, never let a live API call block
the demo.
