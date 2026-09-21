# Participant pipeline image (plan 07 O1).
#
# Adds the parser dependencies the organizers' image omits (openpyxl,
# python-docx, pymupdf) and copies the app + tools. The dataset and ground
# truth are mounted, never baked in.
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

RUN mkdir -p /state /outbox

ENV DATA_DIR=/data \
    STATE_DIR=/state \
    OUTBOX_DIR=/outbox \
    APP_PORT=8001 \
    SCORED_RUN=0

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; port=os.environ.get('APP_PORT','8001'); sys.exit(0 if urllib.request.urlopen(f'http://localhost:{port}/health').status==200 else 1)"

CMD ["sh", "-c", "python -m uvicorn app.server:app --host 0.0.0.0 --port ${APP_PORT:-8001}"]
