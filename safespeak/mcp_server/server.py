"""SafeSpeak's own MCP server. Agents reach tools ONLY through this.

Run standalone:  python -m safespeak.mcp_server   (stdio transport)
ADK starts it as a subprocess via McpToolset (see agents/verifier.py).
Each tool returns a VerifierFinding, sent as MCP structured content, so the
result is typed end to end.
"""

from mcp.server.mcpserver import MCPServer

from safespeak.mcp_server.reputation_tool import domain_reputation as _reputation
from safespeak.mcp_server.whois_tool import domain_age as _age
from safespeak.schemas import VerifierFinding

server = MCPServer("safespeak-tools")


@server.tool()
def domain_age(indicator: str) -> VerifierFinding:
    """How long ago a domain was registered (RDAP/WHOIS). Pass a URL, email or domain."""
    return _age(indicator)


@server.tool()
def domain_reputation(indicator: str) -> VerifierFinding:
    """Check a domain against phishing blocklists and for brand lookalikes. Pass a URL, email or domain."""
    return _reputation(indicator)


if __name__ == "__main__":
    server.run()
