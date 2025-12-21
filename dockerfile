# syntax=docker/dockerfile:1

FROM dhi.io/python:3-debian13-dev AS build-stage

ENV LANG=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .

RUN python -m venv /app/venv

RUN pip install --no-cache-dir -r ./requirements.txt

FROM dhi.io/python:3-debian13-sfw-dev AS runtime-stage

EXPOSE 8000

RUN apt update -y && apt install git -y

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

COPY --from=build-stage /app/venv /app/venv
COPY /app .

CMD ["python3", "-m", "uvicorn", "app:app", "--host=0.0.0.0", "--port=8000"]