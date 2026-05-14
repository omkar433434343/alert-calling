FROM python:3.11-slim

WORKDIR /app

# Install system dependencies needed for asyncpg / psycopg builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Do NOT run alembic here — no DB available at build time on Render.
# Migrations run via the Render "Pre-Deploy Command" setting.

CMD ["python", "main.py"]