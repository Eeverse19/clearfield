"""Shared --country handling for pipeline CLIs."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.profiles import load_country  # noqa: E402


def country_arg() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", required=True, help="country profile id, e.g. laos")
    args = parser.parse_args()
    return load_country(args.country)


def not_implemented(stage: str, profile: dict, needs: str) -> None:
    sys.exit(
        f"[{stage}] country={profile['id']} demo_area={profile['demo_area']!r}: "
        f"not implemented yet (scaffold). Needs: {needs}."
    )
