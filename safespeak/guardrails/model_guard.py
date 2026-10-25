"""Model guardrail: before_model callback on every LLM agent.

Enforces the blackboard rule at the last possible point, right before the
request leaves for Ollama:
  - ADK normally sends the user's chat message and other agents' replies as
    conversation turns. We drop those, so an agent's ONLY input is the typed
    slice of the CaseRecord placed in its instruction.
  - Tool call/response turns are kept (tool-using agents need them).
  - The instruction is re-redacted as defence in depth.
"""

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from safespeak.guardrails.redaction import redact

_TASK_TURN = "Process the INPUT in your instructions. Reply with one JSON object only."


def isolate_llm_request(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """Replace chat history with one fixed task turn; keep tool turns."""
    tool_turns = [c for c in llm_request.contents if _is_tool_turn(c)]
    task = types.Content(role="user", parts=[types.Part(text=_TASK_TURN)])
    llm_request.contents = [task, *tool_turns]

    instruction = llm_request.config.system_instruction
    if isinstance(instruction, str):
        llm_request.config.system_instruction = redact(instruction)[0]
    return None


def _is_tool_turn(content: types.Content) -> bool:
    return any(p.function_call or p.function_response for p in content.parts or [])
