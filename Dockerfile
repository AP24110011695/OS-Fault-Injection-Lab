FROM python:3.11-slim

# Install system dependencies: stress-ng for CPU/memory stress, procps for process utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    stress-ng \
    procps \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Run target heartbeat app by default
CMD ["python", "-m", "target.heartbeat_app"]
