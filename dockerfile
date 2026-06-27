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
FROM python:3.13-slim-bookworm AS build-stage

ENV LANG=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .

RUN python -m venv /app/venv

RUN pip install --no-cache-dir -r ./requirements.txt

# Install ansible in the venv
RUN pip install --no-cache-dir ansible pywinrm

# --- Stage 3: Runtime ---
FROM python:3.13-slim-bookworm AS runtime-stage

ARG BUILD_COMMIT=unknown

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
RUN ansible-galaxy collection install vultr.cloud community.general community.docker community.crypto community.dns ansible.windows community.windows microsoft.ad

# Patch vultr.cloud 1.14.0 for ansible-core 2.21+: the module JSON-encodes its
# request body but never sets Content-Type, so fetch_url now labels it
# application/x-www-form-urlencoded and Vultr rejects it ("Invalid form-encoded
# data" / "Missing name field"). Inject the missing header.
RUN python3 - <<'PY'
import glob, os, sys
import ansible_collections
paths = []
for base in ansible_collections.__path__:
    paths += glob.glob(os.path.join(base, "vultr/cloud/plugins/module_utils/vultr_v2.py"))
if not paths:
    sys.exit("vultr_v2.py not found")
for f in paths:
    s = open(f).read()
    if '"Content-Type"' in s:
        continue
    needle = '            "Accept": "application/json",\n        }'
    add = '            "Accept": "application/json",\n            "Content-Type": "application/json",\n        }'
    if needle not in s:
        sys.exit("header block not found in %s" % f)
    open(f, "w").write(s.replace(needle, add, 1))
    print("patched", f)
PY

# Write build info
RUN echo "{\"commit\": \"${BUILD_COMMIT}\", \"built_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > /app/BUILD_INFO

# Create directories that symlinks will target
RUN mkdir -p /inventory /outputs

CMD ["python3", "-m", "uvicorn", "app:app", "--host=0.0.0.0", "--port=8000"]
