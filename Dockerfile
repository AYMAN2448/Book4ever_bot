FROM python:3.10-slim

ENV AIOHTTP_NO_EXTENSIONS=1 \
    CRYPTOGRAPHY_DONT_BUILD_RUST=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

COPY bot.py .
RUN mkdir -p books

CMD ["python", "bot.py"]
