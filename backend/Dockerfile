FROM python:3.13-slim

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Railway assigns $PORT dynamically — must not hardcode
ENV PORT=8000
# Tune worker count via WEB_CONCURRENCY in the hosting platform
ENV WEB_CONCURRENCY=2

# --timeout-graceful-shutdown 30: on SIGTERM, let in-flight streams drain for
#   up to 30s instead of dropping them mid-response.
# --proxy-headers / --forwarded-allow-ips=*: trust Railway's edge headers so
#   client IPs and protocols are seen correctly (needed for accurate logs).
CMD uvicorn main:app \
    --host 0.0.0.0 \
    --port $PORT \
    --workers $WEB_CONCURRENCY \
    --timeout-keep-alive 120 \
    --timeout-graceful-shutdown 30 \
    --proxy-headers \
    --forwarded-allow-ips="*" \
    --access-log
