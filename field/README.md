# field/ — offline field triage (stub)

`triage.py` will turn a field photo + GPS + Lao/Khmer notes into a
structured find record (Muse Glimmer, local, no connectivity) that
syncs into the same `finds` table the backend writes. Currently a
stub raising NotImplementedError (TASKS P1-3).

`prompts/` holds the triage prompt notes. Hard rule: ambiguous finds
escalate to a human; the app never instructs anyone to approach a
suspected live item.
