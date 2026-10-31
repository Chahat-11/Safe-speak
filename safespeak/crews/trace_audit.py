"""Trace Audit crew: turns measured agent metrics into findings and advice.

Code computes every number (crews/data.py); the crew only interprets them.
"""

from __future__ import annotations

from pathlib import Path

from safespeak.crews.runtime import local_llm

from crewai import Agent, Crew, Process, Task  # noqa: E402

from safespeak import config  # noqa: E402
from safespeak.crews.data import summarise_trace  # noqa: E402
from safespeak.schemas import TraceAudit, TraceSummary  # noqa: E402

OUTPUT = Path("results/trace_audit.json")


def build_crew(summary: TraceSummary) -> Crew:
    llm = local_llm()
    analyst = Agent(
        role="Pipeline Performance Analyst",
        goal="Explain where time and tokens go",
        backstory="You read agent metrics and only state what the numbers show.",
        llm=llm, allow_delegation=False, verbose=False,
    )
    advisor = Agent(
        role="Reliability Advisor",
        goal="Recommend the most valuable small improvements",
        backstory="You favour simple changes backed by the numbers.",
        llm=llm, allow_delegation=False, verbose=False,
    )
    read = Task(
        description=f"Metrics (JSON):\n{summary.model_dump_json()}\n\nState the 3 most important facts. Quote the numbers.",
        expected_output="3 facts with numbers.",
        agent=analyst,
    )
    advise = Task(
        description="Using those facts, give the findings and up to 3 recommendations.",
        expected_output="A JSON object with `findings` and `recommendations` lists.",
        agent=advisor,
        context=[read],
        output_pydantic=TraceAudit,
    )
    return Crew(agents=[analyst, advisor], tasks=[read, advise], process=Process.sequential, verbose=False, tracing=False)


def run(trace_path: Path = config.LOG_PATH) -> TraceAudit:
    result = build_crew(summarise_trace(trace_path)).kickoff()
    audit = result.pydantic or TraceAudit.model_validate_json(result.raw)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(audit.model_dump_json(indent=2), encoding="utf-8")
    return audit
