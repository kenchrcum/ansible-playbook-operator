# syntax=docker/dockerfile:1.20-labs

# Optional: pin base image by digest for enhanced security and reproducibility
# When DIGEST is provided, it takes precedence over tag
# Usage: docker build --build-arg BASE_DIGEST=sha256:abc123... .
ARG BASE_DIGEST=""
FROM python:3.14-alpine${BASE_DIGEST:+@${BASE_DIGEST}} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Build args
ARG PIP_NO_CACHE_DIR=1
ARG PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk add --no-cache gcc musl-dev libffi-dev openssl-dev git

WORKDIR /app
COPY pyproject.toml /app/
COPY requirements.txt /app/
COPY src /app/src

RUN python -m pip install --upgrade pip && \
    python -m pip install .

# Final image
FROM python:3.14-alpine${BASE_DIGEST:+@${BASE_DIGEST}}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:$PATH"

# Upgrade system packages
RUN apk upgrade --no-cache

# Install git and openssh for repository validation
RUN apk add --no-cache git openssh-client

RUN addgroup -S app && adduser -S app -G app
USER app
WORKDIR /app

# Copy the installed site-packages from builder layer
# (keeps image small; we avoid copying source code since package is installed)
COPY --from=base /usr/local /usr/local

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["exec kopf run --standalone -m ansible_operator.main"]
