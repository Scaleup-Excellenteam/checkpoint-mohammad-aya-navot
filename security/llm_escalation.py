"""
security/llm_escalation.py

REAL implementation of the llm_escalation_check callback that DlpEngine
expects, using Ollama's local HTTP API.

*** STATUS: VERIFIED WORKING against a real local model (llama3.2:1b via
Ollama) - confirmed the model follows the "answer YES or NO" instruction
and the response is parsed correctly. The prompt was updated to include
the actual message text (not just term names) so the model can judge
real context, not just a bare list of matched words. ***

Usage:
    from security.llm_escalation import ollama_escalation_check
    from security.dlp_engine import DlpEngine
    from security.policy import DlpPolicy

    engine = DlpEngine(DlpPolicy.load(...), llm_escalation_check=ollama_escalation_check)
"""

import json
import urllib.request
import urllib.error
from typing import List

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.2:1b"


def ollama_escalation_check(username: str, recent_hits: List[str], recent_messages: List[str]) -> bool:
    """
    Asks a local LLM whether this user's recent messages look like a
    genuine attempt to leak the recipe, as opposed to incidental/innocent
    conversation that happens to mention the same words.

    Crucially, this sends the LLM the ACTUAL MESSAGE TEXT (`recent_messages`),
    not just the matched term names (`recent_hits`) - a model can't judge
    context ("talking about pizza" vs "leaking the recipe") from a bare
    word list alone.

    Returns True if the LLM agrees this looks like a real leak (engine
    will then block), False otherwise (engine allows through).

    Fails SAFE on any error (network issue, bad response, timeout): if we
    can't get a clear answer from the LLM, we do NOT block - a DLP false
    positive (blocking innocent chat) is disruptive, and this is only the
    escalation path (below block_threshold), not the hard block path.
    """
    quoted_messages = "\n".join(f'- "{m}"' for m in recent_messages)
    prompt = (
        "You are a security filter for a chat app protecting a secret pizza "
        "recipe. A user sent these messages, which matched recipe-related "
        f"keywords ({', '.join(recent_hits)}):\n"
        f"{quoted_messages}\n\n"
        "Based on the actual message content above, does this look like a "
        "genuine attempt to leak the secret recipe, as opposed to innocent "
        "conversation that happens to mention these words? "
        "Answer with exactly one word: YES or NO."
    )

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
    }

    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        # can't reach the LLM (not running, wrong port, etc.) - fail safe,
        # don't block on an escalation check we couldn't complete
        return False

    answer = result.get("response", "").strip().upper()
    return answer.startswith("YES")


if __name__ == "__main__":
    print("Testing ollama_escalation_check with a REALISTIC leak scenario...")
    leak_verdict = ollama_escalation_check(
        "testuser",
        ["pizza dough", "secret sauce", "300 degrees"],
        [
            "ok so first you make the dough with 500g flour",
            "then the secret sauce is tomato plus a pinch of sugar",
            "bake it at 300 degrees for 12 minutes exactly",
        ],
    )
    print(f"Leak scenario verdict: {'BLOCK' if leak_verdict else 'ALLOW'}")

    print()
    print("Testing ollama_escalation_check with INNOCENT conversation...")
    innocent_verdict = ollama_escalation_check(
        "testuser",
        ["mozzarella"],
        [
            "I had mozzarella sticks at that new restaurant yesterday, so good",
        ],
    )
    print(f"Innocent scenario verdict: {'BLOCK' if innocent_verdict else 'ALLOW'}")