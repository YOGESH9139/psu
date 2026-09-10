# PHASE 0 — Pre-Demo Sanity Pass

**Purpose:** Prove the environment works before writing a single feature line.  
**Rule:** Fix infra until every checkbox passes. No feature code yet.  
**Stack decisions locked in:**
- Model server: **Ollama** (keep_alive=0 for hot-swap)
- OCR: **Tesseract** (local, pre-staged)
- Sandbox: **pre-warmed restricted container** (no Docker socket in worker)
- Orchestration: **LangGraph** state machine + **LangChain** tools
- Reranker: **BAAI/bge-reranker-v2-m3** (local)
- Embeddings: **BAAI/bge-m3** (local)

**Estimated total time: 2–3 h on your current machine**

---

## 0-A · Docker Compose Stack

- [ ] **0-A-1** Start Docker Desktop; `docker info` returns daemon info without error.  
  **Pass:** No "daemon not running" error.  
  **Fail:** Exit code 1 / cannot connect.

- [ ] **0-A-2** `docker compose up --wait` — all services healthy.  
  **Services:** `api`, `worker`, `postgres`, `redis`, `qdrant`, `ollama`  
  **Pass:** `docker compose ps` shows `(healthy)` for all.  
  **Fail:** Any service unhealthy or restart-looping within 60 s.

- [ ] **0-A-3** All services on `internal: true` network; no external default route.  
  **Pass:** `docker network inspect sovereign_internal` shows `"Internal": true` and lists all containers.  
  **Fail:** Any container on the default bridge or with an external gateway.

- [ ] **0-A-4** Postgres migration runs; `runs` and `audit_events` tables exist.  
  **Pass:** `docker compose exec postgres psql -U sovereign -c "\dt"` lists both tables.  
  **Fail:** Connection refused or zero tables.

- [ ] **0-A-5** Redis PING.  
  **Pass:** `docker compose exec redis redis-cli ping` → `PONG`.

**Est: 30 min**

---

## 0-B · Ollama Model Server

> GPU is 8 GB VRAM. Only one 8B Q4 model can be resident at a time. Swap via `keep_alive: 0`.

- [ ] **0-B-1** Ollama container starts; `GET http://localhost:11434/api/tags` returns 200.

- [ ] **0-B-2** `qwen3:8b` (Q4_K_M) pulled and responds to a minimal prompt.  
  **Pass:** `curl http://localhost:11434/api/generate -d '{"model":"qwen3:8b","prompt":"Reply OK only.","stream":false}'` → non-empty `response` within 120 s.  
  **Fail:** Timeout, OOM in logs, or empty response.

- [ ] **0-B-3** `qwen2.5vl:7b` (Q4_K_M — VL model for OCR/vision) responds to an image prompt.  
  **Pass:** Send a base64 1×1 PNG with prompt → non-empty description.  
  **Fail:** model-not-found or OOM.

- [ ] **0-B-4** Model hot-swap: load qwen3:8b with `keep_alive: 0`, then load qwen2.5vl:7b — both succeed sequentially; VRAM does not OOM.  
  **Pass:** Both curl calls succeed back-to-back; `nvidia-smi` shows VRAM < 8 GB at all times.  
  **Fail:** OOM or second load hangs.

**Est: 45 min (pull time excluded — models must be pre-downloaded)**

---

## 0-C · Model Router (deterministic, no LLM call)

- [ ] **0-C-1** PDF/image + OCR keywords → `multimodal-document` / `qwen2.5vl:7b`, confidence ≥ 0.8.
- [ ] **0-C-2** Code keywords or `.py`/`.js` extension → `coding` / `qwen3:8b`, confidence ≥ 0.8.
- [ ] **0-C-3** `.xlsx` + analysis keywords → `spreadsheet-analysis` / `qwen3:8b`, confidence ≥ 0.8.
- [ ] **0-C-4** Plain text, no file → `general-reasoning` / `qwen3:8b`.
- [ ] **0-C-5** Router JSON is the first SSE event emitted to the UI before any agent step.

**Est: 20 min**

---

## 0-D · Qdrant Vector DB

- [ ] **0-D-1** `curl http://qdrant:6333/collections` from inside `api` container → HTTP 200.
- [ ] **0-D-2** Ingest a test chunk; query it back by phrase → appears in top-5.
- [ ] **0-D-3** Rare keyword query returns the correct chunk (BM25 contributing).

**Est: 15 min**

---

## 0-E · Tesseract OCR

- [ ] **0-E-1** `tesseract --version` inside the `worker` container returns version ≥ 5.
- [ ] **0-E-2** OCR a sample scanned page PNG → at least 20 readable words returned.
- [ ] **0-E-3** Output includes `page_number` and `source_file` metadata.
- [ ] **0-E-4** Zero outbound network calls during OCR (local only).

**Est: 15 min**

---

## 0-F · Pre-warmed Sandbox Container

> No Docker socket in worker. Instead: a long-lived `sandbox` service with `network_mode: none`, read-only rootfs, resource limits; worker sends code to it via a local Unix socket or named pipe.

- [ ] **0-F-1** `sandbox` service starts with `network_mode: none`, `mem_limit: 512m`, `cpus: 1`, `pids_limit: 64`.
- [ ] **0-F-2** `print("sandbox-ok")` executes → stdout `sandbox-ok`, exit 0.
- [ ] **0-F-3** `urllib.request.urlopen("http://8.8.8.8")` → network-unreachable error captured in result.
- [ ] **0-F-4** `time.sleep(120)` → killed at ~60 s, timeout error returned.
- [ ] **0-F-5** Write to `/etc/x` → PermissionError; write to `/workspace/out.txt` → success.

**Est: 20 min**

---

## 0-G · DOCX Round-Trip

- [ ] **0-G-1** `create_approval_docx` with a dummy payload → `.docx` file, size > 5 KB.
- [ ] **0-G-2** `verify_docx` on that file → `{valid: true}`, all mandatory headings found.

**Est: 10 min**

---

## 0-H · Full Offline Boot

- [ ] **0-H-1** Disconnect host internet; `docker compose up --wait` → all services healthy (no remote pulls needed).
- [ ] **0-H-2** `GET /api/sovereignty/status` → `{offline_capable: true, egress_blocked: true}`.
- [ ] **0-H-3** Plain-text summarisation run completes in < 3 min with zero outbound TCP.

**Est: 15 min**

---

## Phase 0 Sign-Off

| Area | Checks | Status |
|------|--------|--------|
| 0-A Docker Compose | 5 | ⬜ |
| 0-B Ollama | 4 | ⬜ |
| 0-C Router | 5 | ⬜ |
| 0-D Qdrant | 3 | ⬜ |
| 0-E Tesseract OCR | 4 | ⬜ |
| 0-F Sandbox | 5 | ⬜ |
| 0-G DOCX | 2 | ⬜ |
| 0-H Offline | 3 | ⬜ |

> **All 31 must pass before Phase 1 begins.**

**Total est: 2.5–3 h**
