"""
test_security.py

Requires Ollama running locally with llama3.2:1b pulled (see project docs) -
Test 3 now calls the REAL local LLM, no mock.
"""

from security.policy import DEFAULT_POLICY
from security.dlp_engine import DlpEngine
from security.llm_escalation import ollama_escalation_check

print("=== Test 1: basic obfuscation resistance ===")
engine = DlpEngine(DEFAULT_POLICY)
for text in ["pizza dough", "p1zz4 d0ugh", "pi22a  dooough", "PIZZA-DOUGH"]:
    v = engine.check_message("tester", text)
    print(f"  {text!r:30} -> hits={v.matched_terms} score={v.score:.1f} action={v.action}")

print()
print("=== Test 2: leak split across two 'chats' (same username, different rooms) ===")
engine2 = DlpEngine(DEFAULT_POLICY)
fragments = [
    ("room1", "add the mozzarella first"),
    ("room2", "then a bit of secret sauce"),
    ("room1", "bake at 3OO d3gr33s"),
]
for room, text in fragments:
    v = engine2.check_message("alice", text)
    print(f"  [{room}] {text!r:35} -> score={v.score:.1f} action={v.action} hits={v.matched_terms}")

print()
print("=== Test 3: escalation to the REAL local LLM (llama3.2:1b via Ollama) ===")
print("(this calls a real model - may take a few seconds)")

print()
print("--- 3a: realistic leak scenario ---")
engine3a = DlpEngine(DEFAULT_POLICY, llm_escalation_check=ollama_escalation_check)
leak_messages = [
    "ok so first you make the dough with 500g flour",
    "then the secret sauce is tomato plus a pinch of sugar",
    "bake it at 300 degrees for 12 minutes exactly",
]
for text in leak_messages:
    v = engine3a.check_message("bob", text)
    print(f"  {text!r:55} -> action={v.action} score={v.score:.1f} reason={v.reason!r}")

print()
print("--- 3b: innocent conversation that happens to mention the same words ---")
engine3b = DlpEngine(DEFAULT_POLICY, llm_escalation_check=ollama_escalation_check)
innocent_messages = [
    "I had mozzarella sticks at that new restaurant yesterday, so good",
    "the secret sauce at that burger place is amazing too",
    "my oven only goes up to 300 degrees anyway lol",
]
for text in innocent_messages:
    v = engine3b.check_message("carol", text)
    print(f"  {text!r:55} -> action={v.action} score={v.score:.1f} reason={v.reason!r}")

print()
print("=== Test 4: false positives (substring matching) still fixed ===")
engine4 = DlpEngine(DEFAULT_POLICY)
false_positive_tests = [
    ("I visited the basilica in Rome last year", False),
    ("my basilisk lizard is so cute", False),
    ("the committee approved the oil budget", False),
    ("I saw a mozzarella-shaped cloud today, weird", True),
]
for text, should_hit in false_positive_tests:
    v = engine4.check_message("dave", text)
    got_hit = bool(v.matched_terms)
    status = "OK" if got_hit == should_hit else "FAIL"
    print(f"  [{status}] {text!r:50} hits={v.matched_terms}")