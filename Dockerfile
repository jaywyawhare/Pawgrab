FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./

RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir $(python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(' '.join(d['project']['dependencies']))") && \
    patchright install --with-deps chromium

RUN useradd -r -s /bin/false pawgrab

COPY pawgrab/ pawgrab/
RUN pip install --no-cache-dir .

RUN chown -R pawgrab:pawgrab /app
USER pawgrab

EXPOSE 8000

CMD ["uvicorn", "pawgrab.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--loop", "uvloop", "--http", "httptools"]
