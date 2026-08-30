"""Policy tests for the decide node and the competency plan.

These run without network access or a database: the whole point of putting the
branching in a graph node is that it can be tested on its own.

Run with:  python -m tests.test_decide
"""

from __future__ import annotations

import sys

from graph.nodes import decide
from retrieval.question_bank import QuestionPlan

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        failures.append(f"{name}: {detail}")
        print(f"  FAIL  {name} {detail}")


def base(**overrides) -> dict:
    state = {
        "session_id": "test",
        "turn_index": 1,
        "competency": "system_design",
        "question": "Design a rate limiter.",
        "answer": "Token bucket per client in redis.",
        "relevance": 0.9,
        "depth": 0.5,
        "needs_followup": True,
        "action": "probe",
        "probe_hint": "the redis key layout",
        "reason": "",
    }
    state.update(overrides)
    return state


print("shallow answer -> probe, same competency, no new question")
plan = QuestionPlan()
out = decide(base(action="probe", depth=0.4), plan)
check("action is probe", out["action"] == "probe", out["action"])
check("stays on competency", out["next_competency"] == "system_design")
check("no new question issued", out["next_question"] == "")
check("plan untouched", plan.asked == [], str(plan.asked))
check("directive names the hint", "redis key layout" in out["directive"])
check("control label is never spoken", "ACTION:" not in out["directive"])

print("\nstrong answer -> probe is overridden to advance")
plan = QuestionPlan()
out = decide(base(action="probe", depth=0.85), plan)
check("action upgraded to advance", out["action"] == "advance", out["action"])
check("a question was issued", bool(out["next_question"]))
check("strong answer takes the hardest remaining", out["next_competency"] in {"debugging", "tradeoffs"}, out["next_competency"])

print("\nsecond probe on one competency -> advance instead of looping")
plan = QuestionPlan()
out = decide(base(action="probe", depth=0.45, probe_count=1), plan)
check("second probe advances", out["action"] == "advance", out["action"])
check("a new question is issued", bool(out["next_question"]))

print("\nunusable answer -> clarify, never advances")
plan = QuestionPlan()
out = decide(base(action="clarify", depth=0.1), plan)
check("action is clarify", out["action"] == "clarify")
check("no new question issued", out["next_question"] == "")
check("directive does not shame the candidate", "poorly" not in out["directive"].lower())

print("\nadequate answer -> advance to the next uncovered competency")
plan = QuestionPlan()
out = decide(base(action="advance", depth=0.6), plan)
check("action is advance", out["action"] == "advance")
check("takes the first remaining, not the hardest", out["next_competency"] == "role_framing", out["next_competency"])
check("competency marked covered", plan.asked == ["role_framing"], str(plan.asked))

print("\ncoverage is never repeated across a whole session")
plan = QuestionPlan()
seen: list[str] = []
for _ in range(len(plan.questions)):
    out = decide(base(action="advance", depth=0.6), plan)
    seen.append(out["next_competency"])
check("every competency issued exactly once", len(seen) == len(set(seen)), str(seen))
check("plan is exhausted", plan.exhausted)

print("\nexhausted plan -> wrap up rather than repeating questions")
out = decide(base(action="advance", depth=0.6), plan)
check("action is wrap_up", out["action"] == "wrap_up", out["action"])
check("directive closes the interview", "completes the interview" in out["directive"])
check("wrap-up has no control label", "ACTION:" not in out["directive"])

print()
if failures:
    print(f"{len(failures)} FAILED")
    for line in failures:
        print("  -", line)
    sys.exit(1)
print("all decide-policy checks passed")
