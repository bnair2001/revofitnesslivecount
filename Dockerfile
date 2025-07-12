FROM python:3.12-slim AS base

WORKDIR /code
COPY app/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

CMD ["python", "dashboard.py"]