# syntax=docker/dockerfile:1

# --- Stage 1: Build frontend ---
FROM node:20-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
ENV DOCKER_BUILD=1
RUN npm run build

# --- Stage 2: Python dependencies ---
FROM dhi.io/python:3-debian13-dev AS build-stage

ENV LANG=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .

RUN python -m venv /app/venv

RUN pip install --no-cache-dir -r ./requirements.txt

# Install ansible in the venv
RUN pip install --no-cache-dir ansible

# --- Stage 3: Runtime ---
FROM dhi.io/python:3-debian13-sfw-dev AS runtime-stage

EXPOSE 8000

RUN apt update -y && apt install git openssh-client sshpass ca-certificates -y && update-ca-certificates

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

COPY --from=build-stage /app/venv /app/venv
COPY /app .

# Copy built frontend into static directory
COPY --from=frontend-build /frontend/dist/ ./static/

# Install ansible collections
RUN ansible-galaxy collection install vultr.cloud community.general community.docker community.crypto community.dns

# Create directories that symlinks will target
RUN mkdir -p /inventory /outputs

CMD ["python3", "-m", "uvicorn", "app:app", "--host=0.0.0.0", "--port=8000"]
