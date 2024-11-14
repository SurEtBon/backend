#!/bin/bash
echo -n $GCP_SERVICE_ACCOUNT_KEY | base64 -d > $GCP_SERVICE_ACCOUNT_KEY_JSON_FILEPATH
uv run gunicorn main:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000