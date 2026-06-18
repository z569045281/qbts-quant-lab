# QBTS dashboard jobs — Lambda container image (Route A).
# One image, two handlers (publish / quote); each function selects its handler
# via ImageConfig.Command in template.yaml.
#
# Build context is the REPO ROOT (template.yaml sets DockerContext: ..), so the
# COPY paths below are repo-relative. .dockerignore keeps caches / .venv /
# frontend / node_modules out of the image.
FROM public.ecr.aws/lambda/python:3.12

# System libs not in the base image: libgomp (OpenMP runtime) is required by
# lightgbm, which backend.api imports transitively.
RUN dnf install -y libgomp && dnf clean all

# Python deps first so the (slow) vectorbt/numba/lightgbm layer caches across
# code-only rebuilds.
COPY aws/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code, laid out exactly like the repo root so `import publish`,
# `import quote_pusher`, and `from backend.api import ...` all resolve.
COPY backend/        ${LAMBDA_TASK_ROOT}/backend/
COPY publish.py quote_pusher.py ${LAMBDA_TASK_ROOT}/
COPY aws/lambda_handlers.py      ${LAMBDA_TASK_ROOT}/

# Lambda's filesystem is read-only except /tmp. The backend writes JSON/parquet/
# jsonl caches under backend/data/cache and mkdir()s it at import time, so point
# it at /tmp (writable, but ephemeral per cold start).
RUN rm -rf ${LAMBDA_TASK_ROOT}/backend/data/cache \
 && ln -s /tmp/cache ${LAMBDA_TASK_ROOT}/backend/data/cache

# Overridden per-function by ImageConfig.Command; this is just the default.
CMD ["lambda_handlers.publish_handler"]
