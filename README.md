# backend
RESTful API built with FastAPI framework providing endpoints for data access.

<table>
    <thead>
        <tr>
            <th>Environment variables</th>
            <th>Value</th>
            <th>Description</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>FRONTEND_URL</td>
            <td></td>
            <td></td>
        </tr>
        <tr>
            <td>GCP_PROJECT_ID</td>
            <td></td>
            <td></td>
        </tr>
        <tr>
            <td>GCP_SERVICE_ACCOUNT_KEY_JSON_FILEPATH</td>
            <td></td>
            <td></td>
        </tr>
        <tr>
            <td>BQ_DATASET_ID</td>
            <td></td>
            <td></td>
        </tr>
        <tr>
            <td>BQ_TABLE_ID</td>
            <td></td>
            <td></td>
        </tr>
        <tr>
            <td>GCP_SERVICE_ACCOUNT_KEY</td>
            <td></td>
            <td></td>
        </tr>
        <tr>
            <td>DOCKER_GCP_SERVICE_ACCOUNT_KEY_JSON_FILEPATH</td>
            <td></td>
            <td></td>
        </tr>
    </tbody>
</table>

```ShellSession
uv run fastapi dev main.py
```

```ShellSession
uv run gunicorn main:app --worker-class uvicorn.workers.UvicornWorker
```

```ShellSession
docker build -t backend:latest .
```

```ShellSession
docker run --rm \
    -e FRONTEND_URL=$FRONTEND_URL \
    -e GCP_PROJECT_ID=$GCP_PROJECT_ID \
    -e BQ_DATASET_ID=$BQ_DATASET_ID \
    -e BQ_TABLE_ID=$BQ_TABLE_ID \
    -e GCP_SERVICE_ACCOUNT_KEY=$GCP_SERVICE_ACCOUNT_KEY \
    -e GCP_SERVICE_ACCOUNT_KEY_JSON_FILEPATH=$DOCKER_GCP_SERVICE_ACCOUNT_KEY_JSON_FILEPATH \
    -p 8000:8000 \
    backend:latest
```