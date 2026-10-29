FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app
COPY data-pipeline-integrity/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 fitzza
COPY data-pipeline-integrity/integrity_check.py .
RUN chown -R fitzza /app
USER fitzza
ENTRYPOINT ["python", "/app/integrity_check.py"]
