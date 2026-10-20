FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8099
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/api/config')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099", "--proxy-headers", "--forwarded-allow-ips", "*"]
