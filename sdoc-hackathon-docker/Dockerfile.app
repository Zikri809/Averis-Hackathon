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
# Pre-seed so GET /submission + /ui work instantly on cold start (no /run needed).
# The seed lives in data_v2/ (a path proven to reach Render's build context);
# state/ is deliberately never COPY'd (persistent "not found" on Render).
# It is wired to $STATE_DIR/submission.json in the CMD at container start.
COPY data_v2/render_seed_submission.json /srv/render_seed_submission.json

RUN mkdir -p /state /outbox

ENV DATA_DIR=/data \
    STATE_DIR=/state \
    OUTBOX_DIR=/outbox \
    APP_PORT=8001 \
    SCORED_RUN=0

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD sh -c "python -c \"import urllib.request,os,sys; p=os.environ.get('PORT',os.environ.get('APP_PORT','8001')); sys.exit(0 if urllib.request.urlopen('http://localhost:'+str(p)+'/health').status==200 else 1)\""

# Render injects $PORT; local default stays 8001. The seed file is copied into
# $STATE_DIR at start (STATE_DIR may differ from /state in some setups).
CMD ["sh", "-c", "mkdir -p ${STATE_DIR:-/state} && cp /srv/render_seed_submission.json ${STATE_DIR:-/state}/submission.json 2>/dev/null; exec python -m uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8001}"]
