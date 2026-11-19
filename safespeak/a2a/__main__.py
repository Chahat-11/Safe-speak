"""python -m safespeak.a2a serve           start the A2A server (127.0.0.1:8010)
   python -m safespeak.a2a ask "message"   ask it, as another agent would

Host, port and public address: SAFESPEAK_A2A_HOST / _PORT / _PUBLIC_URL (config.py).
"""

import argparse
import asyncio

import uvicorn

from safespeak import config
from safespeak.a2a.client import ask
from safespeak.a2a.server import build_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m safespeak.a2a")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run SafeSpeak as an A2A server")
    ask_cmd = commands.add_parser("ask", help="send one message to the running server")
    ask_cmd.add_argument("text")
    args = parser.parse_args()

    if args.command == "serve":
        if warning := config.exposure_warning(config.A2A_HOST):
            print(warning)
        uvicorn.run(build_app(), host=config.A2A_HOST, port=config.A2A_PORT)
    else:
        print(asyncio.run(ask(args.text)))


if __name__ == "__main__":
    main()
