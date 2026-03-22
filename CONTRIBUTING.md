# Contributing

## Setup

```bash
git clone https://github.com/jaywyawhare/Pawgrab.git
cd Pawgrab
pip install -e ".[dev]"
patchright install chromium
docker run -d -p 6379:6379 redis:7-alpine
cp .env.example .env
```

## Tests & Linting

```bash
pytest tests/ -v
ruff check pawgrab/ tests/
ruff format pawgrab/ tests/
```

## Website

```bash
cd website && npm install && npm run dev
```

## Pull Requests

1. Branch from `master`
2. Run tests and linting
3. Open a PR with a description of what changed and why
