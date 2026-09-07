"""
security/policy.py

The POLICY: configurable data that defines what counts as a violation,
how severe it is, and when to act. Contains NO enforcement logic itself -
that's dlp_engine.py's job. This separation is the "Policy pattern": swap
or edit the ruleset (edit the JSON file, or construct a different
DlpPolicy) without touching the engine code at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class DlpPolicy:
    # terms that indicate a possible leak (case/obfuscation-insensitive -
    # the engine normalizes before matching, policy just lists the terms)
    blacklist_terms: List[str] = field(default_factory=list)

    # score added per distinct blacklist term matched in a single message
    score_per_hit: float = 3.0

    # score decays over time so old activity doesn't permanently flag a user
    decay_per_second: float = 0.05

    # score at which the engine escalates to a deeper check (e.g. local
    # LLM) instead of an immediate hard block - catches ambiguous cases
    escalation_threshold: float = 6.0

    # score at which the engine blocks outright, no escalation needed
    block_threshold: float = 10.0

    # after an LLM escalation check clears a user, how many seconds before
    # we're willing to call the (expensive) LLM check again for them,
    # instead of re-checking on literally every subsequent message
    escalation_cooldown_seconds: float = 30.0

    @staticmethod
    def load(path: str) -> "DlpPolicy":
        """Load a policy from a JSON file - lets the ruleset be edited
        without redeploying code."""
        data = json.loads(Path(path).read_text())
        return DlpPolicy(**data)

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.__dict__, indent=2))


# A reasonable default policy for local testing - real blacklist terms
# get finalized in the Day 2 class session per the assignment brief.
DEFAULT_POLICY = DlpPolicy(
    blacklist_terms=[
        "pizza dough", "secret sauce", "300 degrees",
        "olive oil", "mozzarella", "basil", "san marzano",
    ],
    score_per_hit=3.0,
    decay_per_second=0.05,
    escalation_threshold=6.0,
    block_threshold=10.0,
)