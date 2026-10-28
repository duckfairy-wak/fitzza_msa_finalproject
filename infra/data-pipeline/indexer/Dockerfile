# Must equal the recommendation-service image running on the node: the single 20 GB node already
# holds its ~3.4 GB torch layers, so only the small layers below are pulled (a different base
# filled the disk on 2026-10-28). Check with:
#   kubectl -n fitzza get pods -l app.kubernetes.io/name=recommendation-service \
#     -o jsonpath="{.items[0].status.containerStatuses[0].imageID}"
ARG BASE_IMAGE=414901227428.dkr.ecr.ap-northeast-2.amazonaws.com/fitzza/recommendation-service@sha256:2876736712d9b089a95e1ca0d5245433b4fe9295fc9962e0c9c34eb42c76bc49
FROM ${BASE_IMAGE}
USER 0
WORKDIR /pipeline
COPY crawler/requirements-cloud.txt ./requirements-cloud.txt
RUN pip install --no-cache-dir -r requirements-cloud.txt
COPY indexer/requirements.txt ./requirements-indexer.txt
RUN pip install --no-cache-dir -r requirements-indexer.txt
COPY index_to_qdrant.py ./index_to_qdrant.py
COPY crawler/src/review_gate.py ./review_gate.py
COPY indexer/entrypoint.py ./entrypoint.py
COPY indexer/vector_points.py indexer/embed_job.py indexer/import_job.py indexer/switch_alias.py ./
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=/work/huggingface
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["python", "/pipeline/entrypoint.py"]
