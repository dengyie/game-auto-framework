FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_SYSTEM_PYTHON=1

# Install essential runtime tools (ADB for emulator bridge, OpenCV GL libs, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    adb \
    libgl1 \
    libglib2.0-0 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy project definition and install dependencies
COPY pyproject.toml README.md ./
RUN uv pip install -e .

# Copy source code and default plugins
COPY core/ ./core/
COPY scheduler/ ./scheduler/
COPY cluster/ ./cluster/
COPY config/ ./config/
COPY plugins/ ./plugins/
COPY server/ ./server/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY main.py ./

RUN mkdir -p logs screenshots reports

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "main.py", "server", "--host", "0.0.0.0", "--port", "8000"]
