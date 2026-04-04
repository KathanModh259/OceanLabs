FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV CC=gcc
ENV CXX=g++

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    python3-dev \
    ffmpeg \
    libsndfile1 \
    libportaudio2 \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.cloud.txt /tmp/requirements.cloud.txt
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /tmp/requirements.cloud.txt

COPY . /app

# Ensure Chromium is present for browser automation paths.
RUN python -m playwright install chromium

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn backend.api_server:app --host 0.0.0.0 --port ${PORT:-8000}"]
