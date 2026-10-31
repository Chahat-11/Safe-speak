"""Pattern Mining crew: proposes catalogue rules for scams we currently miss.

Analyst finds recurring tactics -> Rule Author turns them into cue phrases.
Code then measures each proposal on dev + hard negatives. Nothing is merged
automatically: a human reads data/proposed_patterns.json and decides.
"""

from __future__ import annotations

from pathlib import Path

from safespeak.crews.runtime import local_llm

from crewai import Agent, Crew, Process, Task  # noqa: E402

from safespeak.crews.data import measure, missed_scams  # noqa: E402
from safespeak.schemas import MissedScams, PatternProposals, ProposalEvidence  # noqa: E402

OUTPUT = Path("data/proposed_patterns.json")


def build_crew(scams: MissedScams) -> Crew:
    llm = local_llm()
    analyst = Agent(
        role="Scam Tactic Analyst",
        goal="Find tactics that recur across scam messages",
        backstory="You study Indian SMS and email fraud.",
        llm=llm, allow_delegation=False, verbose=False,
    )
    author = Agent(
        role="Detection Rule Author",
        goal="Turn tactics into short phrases that identify them",
        backstory="You write precise rules that do not fire on normal bank or delivery messages.",
        llm=llm, allow_delegation=False, verbose=False,
    )
    find = Task(
        description=f"Messages (JSON):\n{scams.model_dump_json()}\n\nList up to 3 tactics that appear in several of them.",
        expected_output="Up to 3 tactics, one sentence each.",
        agent=analyst,
    )
    write = Task(
        description=(
            "For each tactic write a proposal with a name, the tactic, and cue_groups: at least 2 groups "
            "of short phrases copied from the messages. A message must contain one phrase from EVERY group "
            "to match, so use groups for different parts of the trick, e.g. [[\"prize\",\"reward\"],[\"claim\"]]."
        ),
        expected_output="A JSON object with a `proposals` list.",
        agent=author,
        context=[find],
        output_pydantic=PatternProposals,
    )
    return Crew(agents=[analyst, author], tasks=[find, write], process=Process.sequential, verbose=False, tracing=False)


def run(sample: int = 30, seed: int = 0) -> list[ProposalEvidence]:
    result = build_crew(missed_scams(sample, seed)).kickoff()
    proposals = result.pydantic or PatternProposals.model_validate_json(result.raw)
    evidence = [measure(p) for p in proposals.proposals]
    OUTPUT.write_text("[\n" + ",\n".join(e.model_dump_json(indent=2) for e in evidence) + "\n]\n", encoding="utf-8")
    return evidence
