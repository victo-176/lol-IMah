FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Force pip upgrade first (cache-bust layer)
RUN pip install --upgrade pip setuptools wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Verify aiohttp has ClientWSTimeout (required by python-engineio)
RUN python -c "from aiohttp import ClientWSTimeout; print('aiohttp OK:', ClientWSTimeout)"

COPY src/ ./src/

RUN mkdir -p /app/data

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socketio; print('ok')" || exit 1

CMD ["python", "-m", "src"]
