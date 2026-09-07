"""
security/dlp_engine.py

The ENGINE: enforcement logic that reads a DlpPolicy but contains no
hardcoded rules itself. Given any DlpPolicy, this code works the same way -
that's what makes the split useful (server code stays the same even if
the policy file changes).

Server usage (conceptually - actual wiring is Navot's server.py):

    from security.policy import DlpPolicy
    from security.dlp_engine import DlpEngine

    policy = DlpPolicy.load("security/dlp_policy.json")
    dlp = DlpEngine(policy)

    # in the CHAT message handler, BEFORE broadcasting:
    verdict = dlp.check_message(username, msg.content)
    if verdict.action == "block":
        await websocket.send(make_error(verdict.reason, code="DLP_BLOCKED"))
        continue
    elif verdict.action == "escalate":
        # optional: run a local LLM check on recent context; if it also
        # flags a leak, treat as blocked, otherwise allow
        ...
    # else action == "allow" -> proceed to broadcast as normal
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .policy import DlpPolicy

# leetspeak / common substitutions -> canonical letter
_LEET_MAP = {
    "0": "o", "1": "i", "2": "z", "3": "e", "4": "a", "5": "s",
    "7": "t", "8": "b", "@": "a", "$": "s", "!": "i",
}
_SEPARATOR_PATTERN = re.compile(r"[\s\-_.,!?]")
_REPEAT_PATTERN = re.compile(r"(.)\1+")

# tiny tolerance for threshold comparisons - without this, a score that
# should land EXACTLY on a threshold (e.g. 2 hits * 3.0 = 6.0, equal to
# escalation_threshold=6.0) can fall a hair short (e.g. 5.99997) purely
# because _apply_decay always subtracts *some* elapsed time, even the
# sub-millisecond gap between two rapid successive calls - this repeatedly
# caused confusing "score looks like it should have triggered but didn't"
# results during testing (measured drift ~3e-5 in practice, so this needs
# to be comfortably larger than that, while still tiny relative to a
# typical score_per_hit of a few points)
_THRESHOLD_EPSILON = 1e-3


def normalize(text: str) -> str:
    """Lowercase, substitute leetspeak, collapse repeated characters."""
    text = text.lower()
    text = "".join(_LEET_MAP.get(ch, ch) for ch in text)
    text = _REPEAT_PATTERN.sub(r"\1", text)
    return text


@dataclass
class DlpVerdict:
    action: str              # "allow" | "escalate" | "block"
    reason: str
    matched_terms: List[str] = field(default_factory=list)
    score: float = 0.0


class DlpEngine:
    """
    Tracks a rolling suspicion score PER USERNAME, across every room/message
    they send - this is what catches a leak split across multiple chats
    ("half the recipe in chat1, half in chat2"): the score accumulates
    regardless of which room each fragment was sent in.
    """

    def __init__(self, policy: DlpPolicy, llm_escalation_check: Optional[Callable[[str, List[str], List[str]], bool]] = None):
        """
        `llm_escalation_check(username, recent_hits, recent_messages) -> bool`
        is an optional callback: when the score crosses escalation_threshold
        but is still under block_threshold, the engine can call this (e.g.
        to run a local LLM over the user's recent messages) to decide
        whether to actually block.

        Both `recent_hits` (the matched blacklist terms) AND
        `recent_messages` (the actual raw message text that triggered
        those hits) are passed - a real LLM check needs the actual
        sentences to judge context (e.g. "talking about pizza" vs
        "leaking the recipe"), not just a list of term names with no
        surrounding context.

        If not provided, escalation-range scores are allowed through with
        an "escalate" action reported but not enforced - the caller
        (server) can decide what to do with that.
        """
        self.policy = policy
        self.llm_escalation_check = llm_escalation_check
        self._scores: dict[str, float] = defaultdict(float)
        self._last_update: dict[str, float] = defaultdict(lambda: time.time())
        self._recent_hits: dict[str, List[str]] = defaultdict(list)
        self._recent_messages: dict[str, List[str]] = defaultdict(list)
        # after an LLM check clears a user, don't call it again for every
        # subsequent message while their score is still in the escalation
        # range - that would mean one real hit triggers an LLM call on
        # every single message afterwards, including totally innocent ones
        self._escalation_cooldown_until: dict[str, float] = defaultdict(float)

        self._normalized_terms = [
            (term, normalize(_SEPARATOR_PATTERN.sub("", term)))
            for term in policy.blacklist_terms
        ]

    def _apply_decay(self, username: str) -> None:
        now = time.time()
        elapsed = now - self._last_update[username]
        self._scores[username] = max(0.0, self._scores[username] - elapsed * self.policy.decay_per_second)
        self._last_update[username] = now

    def _match_blacklist(self, text: str) -> List[str]:
        """
        Tokenizes the message into words, then checks EXACT matches
        (after normalization) against small sliding windows of adjacent
        tokens - not a substring search across the whole message.

        This deliberately fixes two problems a naive "does the normalized
        term appear anywhere in the normalized whole message" check has:
          1. False positives from substrings inside unrelated real words
             (e.g. "basil" matching inside "basilica").
          2. Unrelated distant words in a long message accidentally
             gluing together into something that looks like a match.

        It still catches obfuscation split across a few adjacent tokens
        (e.g. "pi zz a", "p1zz4  d0ugh") because windows join 1..N
        consecutive tokens before normalizing and comparing.
        """
        # split on whitespace AND common punctuation - these are all
        # legitimate word boundaries (e.g. "mozzarella-shaped" should be
        # treated as two words: "mozzarella" and "shaped", not glued into
        # one token that then fails an exact match)
        tokens = [t for t in re.split(r"[\s\-_.,!?]+", text.strip()) if t]

        hits = []
        for original_term, target in self._normalized_terms:
            found = False
            max_window = min(len(tokens), 6)  # bound the search - a few adjacent words is enough
            for window_size in range(1, max_window + 1):
                for start in range(0, len(tokens) - window_size + 1):
                    joined = "".join(tokens[start:start + window_size])
                    if normalize(joined) == target:
                        found = True
                        break
                if found:
                    break
            if found:
                hits.append(original_term)
        return hits

    def check_message(self, username: str, text: str) -> DlpVerdict:
        self._apply_decay(username)

        hits = self._match_blacklist(text)
        if hits:
            self._scores[username] += len(hits) * self.policy.score_per_hit
            self._recent_hits[username].extend(hits)
            self._recent_messages[username].append(text)

        score = self._scores[username]

        if score >= self.policy.block_threshold - _THRESHOLD_EPSILON:
            return DlpVerdict(
                action="block",
                reason=f"Sensitive content detected (score {score:.1f})",
                matched_terms=hits,
                score=score,
            )

        if score >= self.policy.escalation_threshold - _THRESHOLD_EPSILON:
            now = time.time()
            if now < self._escalation_cooldown_until[username]:
                # already checked recently and got cleared - don't spam
                # the (potentially expensive) LLM on every message
                return DlpVerdict(action="allow", reason="in escalation cooldown", matched_terms=hits, score=score)

            if self.llm_escalation_check is not None:
                should_block = self.llm_escalation_check(
                    username, self._recent_hits[username], self._recent_messages[username]
                )
                if should_block:
                    return DlpVerdict(
                        action="block",
                        reason="Sensitive content confirmed by deeper review",
                        matched_terms=hits,
                        score=score,
                    )
                # LLM cleared it - start a cooldown so we don't re-check
                # every message while the score naturally decays
                self._escalation_cooldown_until[username] = now + self.policy.escalation_cooldown_seconds
                return DlpVerdict(action="allow", reason="cleared by escalation check", matched_terms=hits, score=score)

            return DlpVerdict(
                action="escalate",
                reason=f"Score {score:.1f} crossed escalation threshold, no escalation handler configured",
                matched_terms=hits,
                score=score,
            )

        return DlpVerdict(action="allow", reason="", matched_terms=hits, score=score)