ARG PYTHON_IMAGE=python:3.13.15-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv

RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /build
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src ./src
RUN python -m pip install --no-compile .

FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 falcon \
    && useradd --uid 10001 --gid falcon --no-create-home --shell /usr/sbin/nologin falcon

COPY --from=builder --chown=falcon:falcon /opt/venv /opt/venv
USER 10001:10001
WORKDIR /app
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "falcon_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "falcon_api.core.event_loop:create_psycopg_compatible_event_loop", "--no-access-log", "--timeout-graceful-shutdown", "20"]
