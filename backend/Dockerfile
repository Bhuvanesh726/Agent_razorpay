# Backend: FastAPI + the agent harness, served by uvicorn.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is used by the compose healthcheck, not by the app itself.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first: this layer is cached and only rebuilt when
# requirements.txt changes, so ordinary code edits rebuild in seconds.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The SQLite file lives on a named volume mounted here (see
# docker-compose.yml), so orders and agents survive `docker compose down`.
# An absolute path — four slashes after "sqlite:" — because the working
# directory a script runs from must not decide where the database is.
RUN mkdir -p /app/appdata
ENV DATABASE_URL=sqlite:////app/appdata/razorpay_agent.db

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8842
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8842"]
