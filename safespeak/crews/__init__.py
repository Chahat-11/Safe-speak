"""CrewAI offline crews. Run in their own venv (.venv-crews), never in the live service.

CrewAI needs older mcp/pydantic versions than our MCP server, so the two
frameworks live in separate environments, which also keeps offline work out
of the live path. See requirements-crews.txt.
"""
