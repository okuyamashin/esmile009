FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-calc-nogui \
    libreoffice-writer-nogui \
    ca-certificates \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-vlgothic \
    python3 \
    python3-venv \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /venv

COPY docker/fontconfig/local.conf /etc/fonts/local.conf
RUN fc-cache -fv

ENV PATH="/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY VERSION ./
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=$GIT_COMMIT

COPY app/ ./app/
COPY tests/ ./tests/
COPY test-download/ ./test-download/

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
