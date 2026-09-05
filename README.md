# MineIQ — AI-Powered Mining Report Platform (CIL / CMPDI)

**MineIQ** is an AI-powered document ingestion and reporting platform designed for Coal India Limited (CIL) and Central Mine Planning & Design Institute (CMPDI). It ingests scanned geological survey PDFs, production spreadsheets, and mine site images, automatically generating structured reports via OCR, validation, classification, RabbitMQ event queues, and a self-hosted LLM.

---

## 🏗️ Project Architecture & Monorepo Structure

```
mineiq/
├── docker-compose.yml              # Core container orchestration
├── db/
│   └── init/
│       ├── 001_init.sql            # Postgres Document DB schema initialization
│       ├── 002_add_flags.sql        # Migration adding anomaly flags, duplicates & classification fields
│       └── 003_add_reports.sql      # Migration adding reports table & pipeline error columns
├── services/
│   ├── ingestion-service/          # Python FastAPI service for upload & pipeline orchestration (Port 8000)
│   ├── ocr-service/                # Python FastAPI stateless service for document parsing & OCR (Port 8002)
│   ├── validation-service/         # Python FastAPI service for anomaly & near-duplicate validation (Port 8003)
│   ├── classification-service/     # Python FastAPI agent for LLM tagging & Redis caching (Port 8004)
│   └── report-generation-worker/   # Async consumer worker drafting LLM reports via RabbitMQ & Ollama
├── .env.example                    # Environment variables template
├── .gitignore
└── README.md
```

---

## 🚀 Quick Start (Local Infrastructure Setup)

### 1. Prerequisites
- Docker & Docker Compose installed on your host system.

### 2. Launch All Services
Run the following command from the `mineiq` root directory:

```bash
docker compose up -d --build
```

### 3. One-Time Ollama Model Download
After `docker compose up` completes, pull the `llama3.1` model inside the Ollama container once:

```bash
docker exec -it mineiq-ollama ollama pull llama3.1
```

---

## 🔌 Service Port Registry & Credentials

| Service | Host Port | Credentials / Notes |
|---|---|---|
| **FastAPI Ingestion & Orchestration** | `8000` | Upload & `/process/{document_id}` API (`/docs`) |
| **FastAPI OCR Service** | `8002` | Document OCR & Text Extraction (`/docs`) |
| **FastAPI Validation Service**| `8003` | Anomaly & near-duplicate engine (`/docs`) |
| **FastAPI Classification Service**| `8004` | LLM document tagging & Redis cache (`/docs`) |
| **Ollama LLM Engine** | `11434` | Self-hosted Llama 3.1 LLM server |
| **RabbitMQ Management UI**| `15672` | User: `mineiq`, Pass: `mineiq_pass` |
| **RabbitMQ AMQP** | `5672` | User: `mineiq`, Pass: `mineiq_pass` |
| **MinIO S3 API** | `9000` | Access/Secret: `minioadmin` / `minioadmin` |
| **MinIO Web Console** | `9001` | Access/Secret: `minioadmin` / `minioadmin` |
| **PostgreSQL 16** | `5432` | DB: `mineiq_docs`, User: `mineiq`, Pass: `mineiq_pass` |
| **Redis 7** | `6379` | In-memory cache & key-value storage |

---

## 🧪 End-to-End Pipeline Testing with `curl`

> 💡 **Tip for Windows PowerShell Users:**
> In Windows PowerShell, single quotes `'...'` in `curl` can strip JSON double-quotes. Use `curl.exe -H "Content-Type: application/json" -d "{\"key\":\"val\"}"` or use the main pipeline endpoint `POST /process/{document_id}` which doesn't require a raw JSON body!

### 1. Upload a Document (`POST http://localhost:8000/upload`)
Upload a PDF, spreadsheet, or image file:

```bash
curl -X POST "http://localhost:8000/upload" \
  -F "file=@services/ocr-service/tests/sample_sheet.xlsx"
```

**Expected Response:**
```json
{
  "id": "9a991ae1-b629-463b-8a5e-f450fa2128e7",
  "s3_key": "raw-files/9a991ae1-b629-463b-8a5e-f450fa2128e7/sample_sheet.xlsx",
  "status": "uploaded"
}
```

---

### 2. Trigger End-to-End Orchestrated Processing (`POST http://localhost:8000/process/{document_id}`)
Trigger the pipeline orchestrator on `ingestion-service`. This will:
1. Download raw file from MinIO & run **OCR / Text Extraction** (`ocr-service`).
2. Run **Data Validation & Anomaly Checks** (`validation-service`). If flagged as duplicate/garbled, stops here for manual review.
3. Run **LLM Classification** (`classification-service`) with Redis caching.
4. Publish event message to **RabbitMQ** queue `"document.classified"`.
5. Background worker (`report-generation-worker`) consumes event, drafts technical report via Ollama, and saves it to the `reports` database table.

```bash
curl -X POST "http://localhost:8000/process/9a991ae1-b629-463b-8a5e-f450fa2128e7"
```

**Expected Response:**
```json
{
  "id": "9a991ae1-b629-463b-8a5e-f450fa2128e7",
  "original_filename": "sample_sheet.xlsx",
  "s3_key": "raw-files/9a991ae1-b629-463b-8a5e-f450fa2128e7/sample_sheet.xlsx",
  "source_type": "spreadsheet",
  "status": "classified",
  "doc_type": "production_report",
  "subsidiary": "ECL",
  "urgency": "medium",
  "topic_area": "coal production targets",
  "extracted_text": "=== Sheet: Production Summary ===...",
  "flag_reason": null,
  "failure_reason": null,
  "is_duplicate": false
}
```

---

### 3. Monitoring RabbitMQ & Asynchronous Worker
- Open **RabbitMQ Management UI**: [http://localhost:15672](http://localhost:15672) (User: `mineiq` / Pass: `mineiq_pass`).
- Observe messages flowing through the `"document.classified"` durable queue.
- Confirm the dead-letter queue (`"document.classified.dlq"`) remains empty on successful runs.

---

## 📌 Hackathon Roadmap Note (Days 3–4)

> **Note for Teammates:**
> The core pipeline is now fully connected: **Ingestion → OCR → Validation → Classification → RabbitMQ → Async Report Generation Worker**.
> **Days 3–4 Roadmap**:
> - Dashboard UI frontend & interactive report viewer.
> - Retrieval-Augmented Generation (RAG) vector search engine.
> - Additional async workers: topic modeling worker & urgency triage worker.
> - Notification service & API Gateway / Authentication layer.

## Cross-platform Docker + deterministic demo fixtures

The default Compose file does not require NVIDIA, AMD, Intel Arc, or any other GPU runtime. Ollama runs on CPU when a supported GPU is not exposed. GPU acceleration can be configured separately by a host-specific runtime without making the stack fail on machines that have no GPU.

`demo-seed` is an idempotent synthetic dataset service. It populates MCL/NCL/SECL production records needed for graph, PQ, numeric-RAG and discrepancy demonstrations. The values are explicitly synthetic and are not official CIL data.

Start the full stack:

```bash
docker compose up -d --build
```

Wait for the services to become healthy, then run the integration suite:

```bash
python -m pytest -q
```

The first Ollama startup can take longer on CPU-only machines; the Compose healthcheck and test bootstrap allow for that.

