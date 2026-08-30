from livekit.agents import Agent, StopResponse

from agent.tools import SessionRuntime

INTERVIEWER_INSTRUCTIONS = """
You are ARIES, a professional voice interviewer conducting a practice interview.

Ask exactly one short question at a time, then listen. The adaptive graph owns
question selection and supplies candidate-facing text directly; never invent a
control label or expose evaluation data. Never infer confidence, personality,
honesty, intelligence, or trustworthiness from how someone sounds.
""".strip()


class InterviewerAgent(Agent):
    """Conversational voice interviewer backed by a guarded adaptive graph."""

    def __init__(self, runtime: SessionRuntime) -> None:
        super().__init__(
            instructions=INTERVIEWER_INSTRUCTIONS,
            tools=[],
            allow_interruptions=True,
        )
        self.runtime = runtime

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        """Understand one committed turn, then speak only the graph's safe reply.

        The prior implementation asked a 0.6B model to call a tool and interpret
        its control directive. It sometimes skipped the tool and read the
        control label aloud. This hook keeps deterministic control while the
        evaluator supplies answer-aware acknowledgement and follow-up text.
        """

        transcript = (new_message.text_content or "").strip()
        if not transcript:
            raise StopResponse()

        next_utterance = await self.runtime.score_latest_answer(transcript)
        self.session.say(next_utterance, allow_interruptions=True)
        raise StopResponse()
