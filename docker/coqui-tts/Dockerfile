# ARCHER — Coqui TTS Service (GPU Accelerated)
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Remove any third-party apt sources to avoid issues and install basic dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    git \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Coqui TTS and dependencies
RUN pip3 install --no-cache-dir --upgrade pip
RUN pip3 install --no-cache-dir TTS \
    fastapi \
    uvicorn \
    python-multipart

# Download common models to avoid runtime download (optional, but recommended for speed)
# We'll use XTTS-v2 as it's the current recommendation
ENV COQUI_TOS_AGREED=1

# Expose the API port
EXPOSE 8000

# Start script
COPY main.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
