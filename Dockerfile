FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy all project files
COPY . .

# Force cache invalidation — this line changes with every build
RUN echo "build-v44-cooking-model-fix" > /app/.build_version

# Install dependencies (non-editable for production)
RUN uv pip install --system .

# Ensure start.sh is executable
RUN chmod +x start.sh

# Expose port
EXPOSE 8080

# Single process: FastAPI + ADK (no separate worker)
CMD ["./start.sh"]
