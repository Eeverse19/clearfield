"""Offline field triage (Glimmer, local). Scaffold stub.

Target: photo + GPS + Lao notes, zero connectivity -> one structured find
record in the `finds` schema (db/schema.sql), synced to HQ unchanged.
Anything ambiguous escalates to a human operator; this code never instructs
anyone to approach a suspected live item.
"""


def triage_find(*, photo_ref: str, gps: dict, notes: str, country: str) -> dict:
    raise NotImplementedError(
        "field triage not built: needs local Glimmer via llama.cpp (see field/prompts/README.md)"
    )
