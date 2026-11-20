FROM python:3.11-slim

# Railway runtime single-worker hotfix: retain existing data during schema initialization.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install -r requirements.txt

COPY . .

# Run the public web process as a dedicated non-root user.
RUN groupadd --system gtech && useradd --system --gid gtech --home-dir /app gtech \
    && mkdir -p /app/instance \
    && chown -R gtech:gtech /app
USER gtech

CMD ["sh", "-c", "gunicorn --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT:-8080} app:app"]
