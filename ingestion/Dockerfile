FROM python:3.14-slim

WORKDIR /app

RUN pip install --no-cache-dir chromadb==1.5.9 requests==2.32.3

COPY ingest.py .

ENTRYPOINT ["python", "ingest.py"]
