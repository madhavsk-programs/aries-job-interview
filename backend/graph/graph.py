"""LangGraph wiring.

The branching logic lives in a real graph node rather than an if/else chain
inside the agent, so the decision that makes this interview adaptive is
inspectable, independently testable, and shows up as its own span in traces.
"""

from __future__ import annotations

import functools

from langgraph.graph import END, START, StateGraph

from graph.nodes import decide, fast_evaluate
from graph.state import TurnState
from retrieval.question_bank import QuestionPlan


def build_turn_graph(plan: QuestionPlan):
    """Compile the on-critical-path graph for one session.

    ``plan`` is bound per session because coverage state (which competencies
    have been asked) is session-scoped, and the interview is single-threaded
    per room, so no locking is needed around it.
    """

    builder = StateGraph(TurnState)
    builder.add_node("fast_evaluate", fast_evaluate)
    builder.add_node("decide", functools.partial(decide, plan=plan))

    builder.add_edge(START, "fast_evaluate")
    builder.add_edge("fast_evaluate", "decide")
    builder.add_edge("decide", END)

    return builder.compile()
