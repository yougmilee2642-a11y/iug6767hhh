FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py prompts.py storage.py requirement_contract.py ./
COPY agents ./agents
COPY builder ./builder
COPY evaluation ./evaluation
COPY providers ./providers
COPY tools ./tools
COPY services ./services
COPY integrations ./integrations
COPY meetings ./meetings
COPY track1 ./track1
COPY configs ./configs
COPY static ./static

RUN mkdir -p /app/data

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
