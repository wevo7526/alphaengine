FROM python:3.13-slim

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Railway assigns $PORT dynamically — must not hardcode
ENV PORT=8000

CMD uvicorn main:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 300
