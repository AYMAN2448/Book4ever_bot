FROM python:3.10-slim

# تعطيل بناء امتدادات C لـ aiohttp + منع بناء cryptography عبر Rust
ENV AIOHTTP_NO_EXTENSIONS=1
ENV CRYPTOGRAPHY_DONT_BUILD_RUST=1
ENV CARGO_HOME=/app/.cargo

WORKDIR /app

# تثبيت أدوات النظام الأساسية
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# تثبيت Rust (مطلوب لبعض الحزم)
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# إنشاء دليل cargo قابل للكتابة داخل التطبيق
RUN mkdir -p /app/.cargo

# نسخ ملف المتطلبات
COPY requirements.txt .

# ترقية pip وتثبيت الحزم
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# نسخ الكود والكتب
COPY bot.py .
COPY books ./books

# تشغيل البوت
CMD ["python", "bot.py"]
