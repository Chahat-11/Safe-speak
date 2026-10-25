"""Intake/Parser: turns the (redacted) message into a ParsedMessage.

Reads:  case.message_text  (as ParserInput)
Writes: case.parsed        (status -> PARSED)
It extracts facts only; judging is the Reasoner's job.
"""

from safespeak.agents.common import make_llm_agent
from safespeak.schemas import CaseRecord, CaseStatus, ParsedMessage, ParserInput

PROMPT = """You are the SafeSpeak Parser.
Extract facts from a possibly fraudulent message. Do NOT decide if it is a scam.
- The message may be in English, Hindi or Hinglish. Set `language` to 'en', 'hi' or 'hinglish'.
- Copy URLs, phone numbers and emails exactly as written.
- Placeholders like [OTP] or [ACCOUNT] mean a secret was masked; treat them as present.
- Use empty lists when nothing applies."""


def build_input(case: CaseRecord) -> ParserInput:
    return ParserInput(message_text=case.message_text)


def create_parser(model=None):
    return make_llm_agent(
        name="parser",
        prompt=PROMPT,
        build_input=build_input,
        output_schema=ParsedMessage,
        section="parsed",
        status=CaseStatus.PARSED,
        model=model,
    )
