FROM python:3.13-slim

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Railway assigns $PORT dynamically — must not hardcode
ENV PORT=8000

# Single worker on small Railway instances. Two workers of this stack
# (langchain + pandas + hmmlearn + statsmodels) blow past 512MB and OOM-kill,
# and all in-process state (scan_status_store, analysis_status, data-client
# TTL caches) is per-worker — multi-worker fragments it so polling endpoints
# routinely land on a worker that doesn't see the work the trigger started.
CMD uvicorn main:app \
    --host 0.0.0.0 \
    --port $PORT \
    --timeout-keep-alive 300 \
    --timeout-graceful-shutdown 30 \
    --proxy-headers \
    --forwarded-allow-ips="*"
