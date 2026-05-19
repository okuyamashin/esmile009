FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-calc-nogui \
    libreoffice-writer-nogui \
    ca-certificates \
    fonts-liberation \
    fonts-noto-cjk \
    python3 \
    python3-venv \
 && rm -rf /var/lib/apt/lists/* \
 && fc-cache -fv \
 && python3 -m venv /venv

ENV PATH="/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
