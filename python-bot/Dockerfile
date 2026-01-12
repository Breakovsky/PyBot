FROM python:3.13-slim-bookworm

WORKDIR /app

# Install system dependencies for building Python packages with C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

# Set Python to be unbuffered and add /app to path
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "src/main.py"]
