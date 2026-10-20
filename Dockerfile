FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

# Pick up Debian security fixes newer than the base image.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# pip is only needed at build time: removing it also removes its vendored copies of
# urllib3/msgpack/setuptools, which scanners report as vulnerable.
RUN pip install --no-cache-dir -r requirements.txt && pip uninstall -y pip

COPY app ./app

RUN useradd --system --no-log-init --uid 10001 app
USER app

EXPOSE 8099
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/api/config')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099", "--no-server-header"]
