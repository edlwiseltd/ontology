"""Scripted stand-ins for language models, so the evaluation suite runs offline.

Each factory returns an LLMReasoner over a FunctionChatModel: the same code path a real model takes,
including validation of its answer and fallback to the planner. Swap in "claude" (or your own
provider adapter) in evals.json to evaluate a real model.
"""

from autology.reasoners import FunctionChatModel, LLMReasoner


def _candidates(schema):
    return schema["properties"]["action"]["enum"]


def contrarian():
    """Always picks the last valid action: legal, but rarely what the planner would do."""

    def choose(system, prompt, schema):
        names = _candidates(schema)
        return {"action": names[-1], "rationale": "prefer the last option"}, {"input_tokens": 900, "output_tokens": 30}

    return LLMReasoner(FunctionChatModel(choose, model="scripted-contrarian"), cache_size=0)


def unreliable():
    """Answers with an action that does not exist every other call: exercises the fallback path."""
    state = {"n": 0}

    def choose(system, prompt, schema):
        state["n"] += 1
        if state["n"] % 2:
            return {"action": "skip_all_checks", "rationale": "faster"}
        return {"action": _candidates(schema)[0], "rationale": "first valid option"}

    return LLMReasoner(FunctionChatModel(choose, model="scripted-unreliable"), cache_size=0)
