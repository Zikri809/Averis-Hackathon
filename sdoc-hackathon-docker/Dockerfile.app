# Participant pipeline image (plan 07 O1 + Render live overlay).
#
# Adds the parser dependencies the organizers' image omits (openpyxl,
# python-docx, pymupdf) and copies the app + tools. Locally the dataset is
# mounted via compose (./data_v2:/data:ro); for the Render live prototype the
# 520-email sample (inbox + attachments, ~1.3MB) is baked in below — never the
# ground truth (excluded via .dockerignore).
FROM python:3.13-slim

WORKDIR /srv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements-app.txt .
RUN pip install --no-cache-dir \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    -r requirements-app.txt

COPY app ./app
COPY tools ./tools
COPY pytest.ini ./
COPY tests ./tests
# The organizers' loader is consumed read-only (loader_client wraps it); the
# scoring module is needed by tools/score_local.py. Nothing else is copied.
COPY server/loader.py server/scoring.py ./server/

# Live prototype dataset: 520 inbox JSON + 250 attachments + sample shape.
# ground_truth.json is never copied (see .dockerignore).
COPY data_v2/inbox /data/inbox
COPY data_v2/attachments /data/attachments
COPY data_v2/sample_submission.json /data/sample_submission.json

RUN mkdir -p /state /outbox

ENV DATA_DIR=/data \
    STATE_DIR=/state \
    OUTBOX_DIR=/outbox \
    APP_PORT=8001 \
    SCORED_RUN=0

# Frozen Stage-1 LLM cache (8 calibrated classifications, plan 01 C6). Embedded
# here rather than COPY'd: files under state/ repeatedly failed to reach Render's
# build context ("not found" on a different path every build) while this file
# always does.
RUN printf '%s' 'ew0KICAiMjQ4ZGZlMzEzNmI1ZTI1MDNiYjNhNWVhY2QyYjdkYjliN2I3NGRkZmQ5MDAwMjcxODkxMTI5NzM4MjQ4MjE2NyI6IHsNCiAgICAiY2F0ZWdvcnkiOiAiSU5WT0lDRV9RVUVSWSIsDQogICAgImNvbmZpZGVuY2UiOiAwLjg1DQogIH0sDQogICIzMGJjZmMwMTM1OGU5NzA1NTlmZjJmNjA2MDVjOTI4Yzc1YTc5YWM5ZmJhZjUzYWYxZWE2ZTkzOTRhZmU4YjM2Ijogew0KICAgICJjYXRlZ29yeSI6ICJJTlZPSUNFX1FVRVJZIiwNCiAgICAiY29uZmlkZW5jZSI6IDAuOTUNCiAgfSwNCiAgIjMxMzE1ZmNkNDk1OTY0NjQ1YmMzNmJkZWY4MDMyNTk3M2NkZmFlYWY0M2VjYWViYzhiZDBmYjIwYzIyYmYwOTYiOiB7DQogICAgImNhdGVnb3J5IjogIklOVk9JQ0VfUVVFUlkiLA0KICAgICJjb25maWRlbmNlIjogMC45NQ0KICB9LA0KICAiMzQwMzUyNjFlZDQ2ZDQ2OTY0ZjNkYzY2ZmIxNzU3ZjlkYzBlYjllYTMxNmQ3ZTA4MjJmMWY2ZDI1MmRlYzMyMCI6IHsNCiAgICAiY2F0ZWdvcnkiOiAiSU5WT0lDRV9RVUVSWSIsDQogICAgImNvbmZpZGVuY2UiOiAxLjANCiAgfSwNCiAgIjQ4OTAxNWUzODA4ZGFmYjQ3MjY4YzIzYjQ4OTkxNmIxMThmZGU2NzIzNzI5NzQ1MTY4NDIxNDg5ZTVmZmY1YzciOiB7DQogICAgImNhdGVnb3J5IjogIklOVk9JQ0VfUVVFUlkiLA0KICAgICJjb25maWRlbmNlIjogMC45NQ0KICB9LA0KICAiYmUxN2MxN2RiYjQwNTE3MTVmN2QxNWU0YmY2MjZhZDY4ZTg5ODNmOWY1ZjhiOTZkOTFmNTYzOWQ0YjU2NjgwNCI6IHsNCiAgICAiY2F0ZWdvcnkiOiAiSU5WT0lDRV9RVUVSWSIsDQogICAgImNvbmZpZGVuY2UiOiAwLjk1DQogIH0sDQogICJlMTI5ZjE3MDc1YmUxMzUzOGVkM2Q0OGRmNGQxOWNlNmJmN2E3MGZkZGM2OWM1MmVjMzgxMWU5ZTZkNmIyY2I4Ijogew0KICAgICJjYXRlZ29yeSI6ICJJTlZPSUNFX1FVRVJZIiwNCiAgICAiY29uZmlkZW5jZSI6IDAuOTUNCiAgfSwNCiAgImUxNzYwZGVjZjRjMzlmMjVjNmZkYWE0YzQ2NmRlZDU0NDg3Mjc3OGUwOGU5YWUyNTg5Y2RiYmJmYWE2ODU1ZjEiOiB7DQogICAgImNhdGVnb3J5IjogIklOVk9JQ0VfUVVFUlkiLA0KICAgICJjb25maWRlbmNlIjogMC45DQogIH0NCn0NCg==' | base64 -d > /state/llm_cache.json

# Build-time pre-seed: run the frozen pipeline over the baked dataset so
# GET /submission + /ui work instantly on cold start (no /run needed). Fully
# offline and deterministic (no API key at build time; cache misses fall back to
# rules). Verified locally to reproduce the frozen 520-record submission.
RUN python -m app.run --data /data --out /state/submission.json --no-checkpoint

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD sh -c "python -c \"import urllib.request,os,sys; p=os.environ.get('PORT',os.environ.get('APP_PORT','8001')); sys.exit(0 if urllib.request.urlopen('http://localhost:'+str(p)+'/health').status==200 else 1)\""

# Render injects $PORT; local default stays 8001.
CMD ["sh", "-c", "exec python -m uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8001}"]
