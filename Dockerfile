# syntax=docker/dockerfile:1.7-labs

FROM python:3.13-alpine AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Build args
ARG PIP_NO_CACHE_DIR=1
ARG PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk add --no-cache gcc musl-dev libffi-dev openssl-dev git

WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src

RUN python -m pip install --upgrade pip && \
    python -m pip install .

# Final image
FROM python:3.13-alpine
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install git for repository validation
RUN apk add --no-cache git

RUN addgroup -S app && adduser -S app -G app
USER app
WORKDIR /app

# Copy the installed site-packages from builder layer
# (keeps image small; we avoid copying source code since package is installed)
COPY --from=base /usr/local /usr/local

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["exec kopf run --standalone -m ansible_operator.main"]
