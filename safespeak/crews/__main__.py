"""CLI (use the crews venv):
  .venv-crews/bin/python -m safespeak.crews patterns [--sample 30]
  .venv-crews/bin/python -m safespeak.crews audit
  .venv-crews/bin/python -m safespeak.crews ask "message"   (needs: python -m safespeak.a2a serve)
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m safespeak.crews")
    parser.add_argument("crew", choices=["patterns", "audit", "ask"])
    parser.add_argument("text", nargs="?", help="message to check (for: ask)")
    parser.add_argument("--sample", type=int, default=30, help="missed dev scams shown to the Pattern Mining crew")
    args = parser.parse_args()

    if args.crew == "patterns":
        from safespeak.crews import pattern_mining

        for e in pattern_mining.run(args.sample):
            print(f"{e.proposal.name}: catches {e.scam_hits}/{e.scam_total} dev scams, "
                  f"{e.false_alarms}/{e.legit_total} false alarms")
        print(f"Wrote {pattern_mining.OUTPUT} for human review.")
    elif args.crew == "ask":
        from safespeak.crews import a2a_ask

        print(a2a_ask.run(args.text or ""))
    else:
        from safespeak.crews import trace_audit

        print(trace_audit.run().model_dump_json(indent=2))
        print(f"Wrote {trace_audit.OUTPUT}.")


if __name__ == "__main__":
    main()
