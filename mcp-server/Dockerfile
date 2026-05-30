# AlphaEngine gateway (mcp-server) — standalone. Serves REST (/v1/*) + MCP
# (/mcp) in one process. The deterministic + MCP planes have NO backend
# dependency at runtime (the Decision Gate import in the envelope builder
# degrades gracefully). The agent-job plane (T7) additionally needs the backend
# package + its LLM deps; add those when that lands.
#
# Railway: set the service root to mcp-server/ (build context = mcp-server/).
FROM python:3.10.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app

# AUTH_STUB defaults on for local; production MUST set AUTH_STUB=0 + MCP_API_KEYS.
ENV PORT=8080
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
