FROM python:3.12-slim AS base

WORKDIR /app

# Install system deps for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata first for layer caching
COPY pyproject.toml README.md LICENSE ./

# Install deps (without source — uses only pyproject.toml metadata)
RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir $(python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(' '.join(d['project']['dependencies']))") && \
    playwright install --with-deps chromium

# Copy source
COPY pawgrab/ pawgrab/
COPY cli/ cli/
RUN pip install --no-cache-dir -e .

# Non-root user
RUN useradd -r -s /bin/false pawgrab && chown -R pawgrab:pawgrab /app
USER pawgrab

EXPOSE 8000

CMD ["uvicorn", "pawgrab.main:app", "--host", "0.0.0.0", "--port", "8000"]
