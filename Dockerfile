FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml .
COPY app/ app/

# Install dependencies
RUN uv pip install --system -e .

# Expose port
EXPOSE 8080

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
