# Cached demo responses

The demo must survive an API outage: the Spark agent and Glimmer triage read
this directory first and only call a live model on a cache miss. Every scripted
step in `docs/demo-script.md` gets one cached file here before submission day.

Format (to freeze when the agent lands): one JSON file per scripted step,
named `<moment>-<step>-<lang>.json`, containing the exact response payload the
live path would return plus the score components it was generated from, so a
cached answer can still be checked against the numbers on screen.

Empty for now — no model has run yet, and nothing here may be hand-written to
look like a model output.
