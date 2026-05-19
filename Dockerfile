FROM python:3.9-slim

WORKDIR /app

# تثبيت أدوات البناء الأساسية
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# تعطيل تجميع الامتدادات C لـ aiohttp
ENV AIOHTTP_NO_EXTENSIONS=1

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY books ./books

CMD ["python", "bot.py"]
