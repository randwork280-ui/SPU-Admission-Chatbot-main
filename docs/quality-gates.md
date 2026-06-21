# Quality Gates

The project now has a lightweight quality gate that runs without Docker, Qdrant, OpenAI, or official source documents.

## Local Gate

Run:

```bash
python scripts/quality_check.py
```

This checks:

- Python syntax compilation for repository Python files;
- Arabic/UTF-8 encoding guard;
- evaluation dataset schema validation;
- unit tests for cache keys, telemetry, admin token behavior, manifest/source IDs, and evaluation rules.

Optional frontend build:

```bash
python scripts/quality_check.py --frontend-build
```

The frontend build requires Node dependencies to be installed in `Services/spu-ai-connect-main`.

## CI Gate

The GitHub Actions workflow at `.github/workflows/quality.yml` runs:

- backend quality gate;
- frontend dependency install;
- frontend production build.

## What This Does Not Replace

This gate does not replace:

- Docker Compose integration tests;
- Qdrant contract tests;
- source-backed RAG gold evaluation;
- deployment smoke tests.

Those remain required before production launch.
