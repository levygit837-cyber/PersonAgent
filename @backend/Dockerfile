FROM python:3.13-slim

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency metadata first for layer caching
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install dependencies and the package itself
RUN uv pip install --system -e .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Default command (overridden by docker-compose)
CMD ["personagent", "serve", "--host", "0.0.0.0", "--port", "8000"]
