FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

# Prevent python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create runtime, state, and output directories and set ownership for pwuser
RUN mkdir -p /app/.slc /app/.runtime /app/output && \
    chown -R pwuser:pwuser /app

# Copy application configuration and source code
COPY pyproject.toml .
COPY src/ ./src/

# Switch to non-root pwuser for execution
USER pwuser

# Default entrypoint runs the job loop CLI orchestrator
ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--dry-run"]
