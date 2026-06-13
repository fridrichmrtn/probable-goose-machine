FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# requirements.txt is kept in sync with uv.lock by a pre-commit hook; install
# from it so the image needs no build backend or editable install of the app.
COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

# Prompts live under src/gander/prompts/, so copying src/ pulls them in too.
COPY src/ src/
COPY app.py ./

ENV PYTHONPATH=/app/src
# Unbuffered stdout/stderr so structlog operability events flush immediately;
# otherwise a container kill can swallow the last buffered events — exactly the
# ones that would explain why it died.
ENV PYTHONUNBUFFERED=1
# Gradio's default port; HF Spaces also expects 7860. Bind to all interfaces so
# the container is reachable from the host.
ENV GRADIO_SERVER_NAME=0.0.0.0
EXPOSE 7860

# Liveness: GET Gradio's /config (served once the app is up). slim has no
# curl/wget, so use stdlib urllib. start-period covers import + check_env boot
# before failures count against the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/config', timeout=4).status == 200 else 1)"

# OPENROUTER_API_KEY must be injected at runtime (-e or compose secrets); the
# app calls gander.llm.check_env() at startup and exits if it is unset.
CMD ["python", "app.py"]
