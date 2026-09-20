# Sovereign AI Workbench

A private, fully local AI workbench for organisations whose data can never leave the building. It works the way Claude or Codex do (ask, attach a file, watch an agent plan and act, review the result), but every model, every document and every line of generated code stays on your own machine.

Built for **Smart India Hackathon 2026, Problem Statement SIH26117 (MRPL)**.

> **This is a working prototype, not a deployable product.** It runs completely locally on one workstation, with demo credentials, no login and no hardening for production use. See [Limitations](#limitations).

---

## Why this exists

Refineries, PSUs, defence-linked units and government offices do a lot of routine but sensitive knowledge work: approval notes, engineering calculations, reviews of scanned inspection reports, internal tools. Policy keeps that data on premises, so it either gets done by hand, or someone quietly pastes it into a public AI tool anyway.

Open-weight models are now good enough to build a genuinely useful assistant on. What was missing is something an industrial user can actually sit down and work with. This project is that: a self-hosted, air-gapped workbench that

- picks the right local model for each task **automatically** (a coding request is handled differently from a document summary), with an optional manual override,
- acts as an **agent**: plans, calls tools, checks its own work and iterates, and shows every step,
- reads scanned pages and images on-device (OCR + a vision model),
- grounds its answers in **your own** manuals and SOPs and cites the file and page,
- produces **real deliverables**, such as a Word approval note you can preview and download,
- runs generated code only inside an **isolated sandbox** with no network,
- refuses to finalise anything safety-relevant until **a human approves it**, and
- shows measured proof that nothing goes out.

## What you can do in it

| | |
|---|---|
| **Workspaces** | A setup screen creates a workspace (Plant Maintenance, Engineering & Code, Finance & Procurement, or blank), each with its own reference library and starter tasks. |
| **Ask about a spreadsheet** | "Which machines are running above 85 degrees C?" Exact matching rows are computed by code over the file, not guessed by the model. |
| **Draft an approval note** | Reads the file, searches the workspace library, writes a `.docx` with cited clauses, verifies it, then **waits for your approval**. |
| **Fix code and test it** | The agent writes the fix and runs the tests inside the sandbox. |
| **Scanned reports** | OCR plus a vision model over a scanned PDF (slow on an 8 GB GPU, about 5 minutes). |
| **Follow-ups** | Keep talking about the result ("which of those also breach vibration?"). |
| **Guide** | An in-app page with a hover preview of every feature and a "Try this" button. Anything not built yet is labelled *Roadmap*. |
| **Proof of isolation** | Live status showing the agent and the sandbox cannot reach the internet, measured from inside those containers. |

## How it works

```
Browser (React)  ──►  API (FastAPI)  ──►  Redis queue  ──►  Worker (LangGraph agent)
                          │                                     │
                     PostgreSQL                 ┌───────────────┼────────────────┐
                (runs, audit, approvals)     Ollama          Qdrant           Sandbox
                                          (local models)  (vector search)  (no network)
```

The agent is an explicit state machine: `INTAKE → PREFLIGHT → ROUTE → PLAN → ACT ⇄ OBSERVE → VERIFY → AWAIT_APPROVAL → DELIVER`. It has a fixed allow-list of tools, run-scoped file access, a tool budget and a wall-clock limit, and it cannot record an approval itself: the run blocks until a human decision exists in the database.

- **Models** (served by Ollama): Qwen3 8B for reasoning, coding and summaries; Qwen2.5-VL 7B for scans and images. Only one is resident on the GPU at a time.
- **Routing** is deterministic (file types, extensions, keywords), never another model call. The routing card shows the signals it matched.
- **Retrieval** is hybrid: dense embeddings (BGE-small, baked into the worker image) plus BM25, fused with reciprocal rank fusion, with page-level citations.
- **OCR**: Tesseract 5, running locally.
- **Isolation**: services sit on an `internal` Docker network with no route out; the sandbox runs with `network_mode: none`, a read-only filesystem, dropped capabilities and CPU/memory/PID limits.

---

## Requirements

Developed and tested on **Windows 11 with Docker Desktop (WSL2 backend)**, an **NVIDIA RTX PRO 2000 (Blackwell) laptop GPU with 8 GB VRAM** and 32 GB RAM.

| | Minimum | Tested on |
|---|---|---|
| GPU | NVIDIA, 8 GB VRAM | RTX PRO 2000, 8 GB |
| RAM | 16 GB | 32 GB |
| Free disk | 25 GB (images plus about 11 GB of model weights) | |
| Software | Docker Desktop with GPU support, current NVIDIA driver, Git | Docker Desktop 4.57, WSL 2.6 |
| Internet | **First setup only**, to build images and pull models. Afterwards everything runs offline. | |

Ports used on `127.0.0.1` only: **3000** (UI) and **8000** (API).

> **Windows note:** if Docker Desktop's engine keeps stopping the moment a model loads, Windows may be running out of *virtual memory* (a small custom pagefile plus a large WSL VM). Raise it under System Properties → Advanced → Performance → Virtual memory (for example initial 8192 MB, maximum 12288 MB) and restart.

---

## Setup

```bash
# 1. Build the images (needs internet, takes a few minutes)
docker compose build

# 2. Start the stack
docker compose up -d

# 3. Pull the two models into the local model server (about 11 GB, one time)
docker compose exec ollama ollama pull qwen3:8b
docker compose exec ollama ollama pull qwen2.5vl:7b
```

Open **http://localhost:3000**. On first run you get the workspace setup screen: pick a template, leave "Load the sample documents" ticked and create it. Then use one of the starter tasks. Each one attaches its own sample file.

Check everything is healthy with `docker compose ps`. All services should be `Up`, and the sidebar should show **2/2 models ready** and **No internet access**.

### Run it air-gapped

Once the models are pulled, cut the model server off from the internet:

```bash
docker compose -f docker-compose.yml -f docker-compose.airgap.yml up -d
```

You can then turn Wi-Fi off. Everything keeps working.

### Stop / reset

```bash
docker compose down            # stop, keep data
docker compose down -v         # stop and delete all data, including pulled models
```

---

## Tests

The suite (about 100 tests: routing, tool policy, path safety, document generation and verification, spreadsheet answers, the approval gate) runs inside the worker container, which has Tesseract, PyMuPDF and the embedding model. With the stack running:

```bash
docker cp tests psu-worker-1:/app/tests
docker cp fixtures psu-worker-1:/app/fixtures
docker cp pytest.ini psu-worker-1:/app/pytest.ini
docker exec -w /app psu-worker-1 python -m pytest tests -q
```

The container name follows your folder name (`psu-worker-1` for a folder called `psu`).

## Project layout

```
backend/     FastAPI service, database models, migrations (Alembic)
worker/      LangGraph agent, tools (OCR, spreadsheets, DOCX, sandbox), RAG pipeline
sandbox/     Isolated code runner (no network, read-only)
frontend/    React + Vite UI, served by nginx. Sample files live in public/samples
infra/       models.yaml (model registry and routing config)
fixtures/    Scripts that generate the synthetic demo documents
tests/       Unit and integration tests
docs/        Problem statement and the planning notes from the build
```

## Limitations

- **A prototype, not a product.** Single user, no authentication, demo database credentials in `docker-compose.yml`. Do not expose it to a network.
- **Sized for one 8 GB GPU.** Only one model is loaded at a time, so switching between the text and vision model takes about 20-30 seconds. A scanned-report run takes about 5 minutes.
- **The agent's tool sequence is fixed per task type.** The model fills in the content (queries, findings, recommendations, generated code) from what the tools actually read, but it does not invent new plans.
- **Word output only.** PowerPoint and Excel generation are declared but not implemented.
- **The isolation panel reports measured status, not packet capture.** A live network monitor is on the roadmap.
- **Synthetic data only.** Every sample document is invented and labelled as such.

## Roadmap

A full plan for the next stage (a model registry that can register and benchmark new open-weight models, a planner-driven agent with editable plans, PPT/Excel output, mail and folder connectors, a real network monitor) is in [`docs/build-notes/PLAN_V2.md`](docs/build-notes/PLAN_V2.md).
