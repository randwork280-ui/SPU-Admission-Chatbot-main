# SPU Admission Chatbot

A bilingual English/Arabic RAG chatbot for Syrian Private University admission inquiries. The system uses FastAPI services, Qdrant hybrid retrieval, BGE-M3 embeddings, OpenAI generation, and a Vite React frontend.

## What It Does

- Answers admission questions in Arabic or English.
- Retrieves university document chunks before generation.
- Streams chatbot responses to the frontend.
- Shows source metadata for retrieved chunks.
- Provides an admin dashboard for scanning data and running ingestion.
- Adds collection-versioned retrieval caching, exact FAQ answer caching, query-vector caching, and OpenAI usage telemetry.

## Architecture

```text
Data/*.md
  -> Data Loader
  -> Data Splitting
  -> Embedding Store
  -> Qdrant
  -> RAG Service
  -> QA Chatting API
  -> React Frontend
```

## Required Environment

Copy `.env.example` to `.env` and set real values:

```bash
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1-mini
CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
ADMIN_PASSWORD_HASH=pbkdf2_sha256$replace_salt_hex$replace_digest_hex
ADMIN_TOKEN_SECRET=replace-with-a-long-random-secret-at-least-32-chars
```

Generate the admin password hash with:

```bash
python -c "from Services.Data_Loader.admin_security import hash_password; print(hash_password('replace-this-password'))"
```

## Data Setup

The repository includes a tracked `Data/` directory contract, but real source documents are ignored by default. Add reviewed Markdown files under `Data/`, then update `Data/manifest.json` with source metadata and checksums.

Each manifest entry should include `source`, `language`, `faculty`, `doc_category`, `version`, `official_date`, `checksum`, and `visibility`.

## Run Locally

```bash
docker compose up --build
```

Service URLs:

- Frontend: `http://localhost:5173` when running Vite locally.
- Data Loader: `http://localhost:5001`
- QA Chat API: `http://localhost:5005`
- QA cache stats: `http://localhost:5005/cache/stats`
- Qdrant dashboard: `http://localhost:6333/dashboard`

For the frontend, copy `Services/spu-ai-connect-main/.env.example` to `Services/spu-ai-connect-main/.env.local` if you need custom API URLs.

## Quality Checks

Run the encoding guard before committing Arabic or documentation changes:

```bash
python scripts/check_encoding.py
```

Run the local quality gate:

```bash
python scripts/quality_check.py
```

Run the frontend build from `Services/spu-ai-connect-main`:

```bash
npm run build
```

Validate the evaluation dataset:

```bash
python evaluate_system.py --validate-only
```

Run the smoke evaluation after the backend is running:

```bash
python evaluate_system.py --judge-mode rules --fail-on-threshold
```

## Architecture Decisions

- Full RAG system design: [docs/RAG_SYSTEM_DESIGN.md](docs/RAG_SYSTEM_DESIGN.md)
- Cache strategy: [docs/cache-strategy.md](docs/cache-strategy.md)
- Evaluation docs: [docs/evaluation.md](docs/evaluation.md)
- Evaluation workflow: [evaluation/README.md](evaluation/README.md)
- Quality gates: [docs/quality-gates.md](docs/quality-gates.md)
