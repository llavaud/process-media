# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ffmpeg \
        libimage-exiftool-perl \
        jpeginfo \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install package
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Default workdir for user data
WORKDIR /data

ENTRYPOINT ["process-media"]
CMD ["--help"]
