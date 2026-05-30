"""
Deploy entrypoint — one process, both doors.

Serves the deterministic REST surface (api.py) at the root and the MCP
streamable-HTTP surface (server.py) at /mcp, sharing one core + one auth layer.
The MCP session manager needs its lifespan running, so the parent app owns it.

    uvicorn app:app --host 0.0.0.0 --port $PORT

Note: the /mcp mount + lifespan is the MCP-SDK-recommended FastAPI integration
pattern; verify the MCP handshake end-to-end at first deploy (covered by the
connect-from-Claude test in docs/TEST_FROM_CLAUDE.md).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

import api
import server


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Run the MCP server's session manager for the life of the process.
    async with server.mcp.session_manager.run():
        yield


app = FastAPI(title="AlphaEngine gateway", lifespan=lifespan)

# MCP first so /mcp is not shadowed by the root mount.
app.mount("/mcp", server.app)
# Deterministic REST (/v1/...) at the root.
app.mount("/", api.app)
