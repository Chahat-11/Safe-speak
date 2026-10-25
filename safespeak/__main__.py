"""CLI: python -m safespeak "message text"   (or pipe the message on stdin).

  --json   print the final CaseRecord as indented JSON instead of Markdown.
           Only JSON goes to stdout, so it can be piped (e.g. into jq).
"""

import argparse
import asyncio
import json
import sys

from safespeak.app import AnalysisResult, analyse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m safespeak", description="Analyse a suspicious message.")
    parser.add_argument("message", nargs="*", help="message text (read from stdin if omitted)")
    parser.add_argument("--json", action="store_true", help="print the CaseRecord as JSON instead of Markdown")
    args = parser.parse_args(argv)

    text = " ".join(args.message) or sys.stdin.read()
    result = asyncio.run(analyse(text))
    print(as_json(result) if args.json else as_markdown(result))


def as_json(result: AnalysisResult) -> str:
    """The whole CaseRecord. If the input guardrail blocked the message there
    is no case, so print the block reason in the same JSON shape instead."""
    if result.case is not None:
        return result.case.model_dump_json(indent=2)
    return json.dumps({"case": None, "blocked": True, "message": result.markdown}, indent=2)


def as_markdown(result: AnalysisResult) -> str:
    lines = [result.markdown, "", "---"]
    for m in result.metrics.agents:
        lines.append(f"{m.agent:<12} calls={m.calls} {m.duration_ms:>8.0f} ms  "
                     f"tokens in/out={m.prompt_tokens}/{m.completion_tokens}")
    lines.append(f"case={result.metrics.case_id}  total tokens={result.metrics.total_tokens}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
