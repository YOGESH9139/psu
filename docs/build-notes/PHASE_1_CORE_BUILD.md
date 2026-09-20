# PHASE 1 — Core Build (Hackathon Demo)

**Goal:** Fully demo-ready product. Everything a judge sees in the room.  
**Entry gate:** All Phase 0 checks pass.  
**Exit gate:** Full hero workflow runs end-to-end in < 4 min on the 8 GB GPU.

**Orchestration: LangGraph** for the agent state machine (replaces custom FSM).  
**Memory: LangChain** `ConversationSummaryMemory` backed by Postgres for episodic context within a run.  
**Tools: LangChain** `@tool` wrappers registered into the LangGraph node.

---

## 1-A · Repo Scaffold + Compose Stack
**Deps:** Phase 0 done | **Est: 1 h**

- [ ] **1-A-1** Directory structure: `backend/`, `frontend/`, `worker/`, `infra/`, `fixtures/`, `tests/`
- [ ] **1-A-2** `docker-compose.yml` — services: `api`, `worker`, `postgres`, `redis`, `qdrant`, `ollama`, `sandbox`; all on `internal: true`; `api` binds `127.0.0.1:8000` only
- [ ] **1-A-3** Dockerfiles for `api`, `worker`, `sandbox`; all base images pre-staged
- [ ] **1-A-4** `infra/models.yaml` — both models with `endpoint`, `capabilities`, `preferred_tasks`, `keep_alive: 0`
- [ ] **1-A-5** Alembic migrations: `runs`, `audit_events`, `artifacts`, `approval_decisions`, `knowledge_chunks`

---

## 1-B · Model Registry + Router
**Deps:** 1-A, 0-B | **Est: 1.5 h**

- [ ] **1-B-1** `ModelRegistry`: loads `models.yaml`; `get_model(task_class)`, `swap_model(model_id)` (Ollama `keep_alive: 0` eviction); health-check endpoint
- [ ] **1-B-2** `ModelRouter`: deterministic signal-matching (MIME type, file extension, keyword set) → `{modelId, taskClass, confidence, matchedSignals}`
  - PDF/image/OCR → `multimodal-document` → `qwen2.5vl:7b`
  - `.py`/`.js`/code keywords → `coding` → `qwen3:8b`
  - `.xlsx` + analysis → `spreadsheet-analysis` → `qwen3:8b`
  - default → `general-reasoning` → `qwen3:8b`
- [ ] **1-B-3** Router decision emitted as the **first** SSE event of every run
- [ ] **1-B-4** `GET /api/sovereignty/status` includes model registry state

---

## 1-C · Core FastAPI + SSE
**Deps:** 1-A, 1-B | **Est: 1.5 h**

- [ ] **1-C-1** `POST /api/files` — upload, MIME check, store to `volumes/uploads/{run_id}/`, return `{fileId, hash, mimeType}`
- [ ] **1-C-2** `POST /api/knowledge/ingest` — accept file ID, kick off RAG ingestion job
- [ ] **1-C-3** `POST /api/runs` — create run, enqueue to worker, return `{runId, status: "queued"}`
- [ ] **1-C-4** `GET /api/runs/{id}/events` — SSE; events: `router_decision`, `state_change`, `tool_call`, `tool_result`, `awaiting_approval`, `run_complete`, `run_error`
- [ ] **1-C-5** `GET /api/runs/{id}/artifacts` — list artifacts with download URLs
- [ ] **1-C-6** `POST /api/runs/{id}/approval` — write `approval_decisions` + audit row; unblock the waiting LangGraph run
- [ ] **1-C-7** `GET /api/sovereignty/status` — model endpoints, egress check, network status, audit tail

---

## 1-D · LangGraph Agent State Machine
**Deps:** 1-B, 1-C, 1-H (tool registry) | **Est: 3 h**

> LangGraph replaces a hand-rolled FSM. Each state is a LangGraph `StateNode`; transitions are explicit edges, not framework magic.

- [ ] **1-D-1** LangGraph graph with exactly these nodes mapped to PLAN.md states:
  `INTAKE → PREFLIGHT → ROUTE → PLAN → ACT → OBSERVE → VERIFY → AWAIT_APPROVAL → DELIVER`
- [ ] **1-D-2** `AgentState` TypedDict: `{run_id, goal, file_ids, task_class, model_id, plan, tool_calls, observations, artifacts, approval_decision, audit_events, iteration_count, messages}`
- [ ] **1-D-3** **INTAKE**: validate input, record initial audit event, attach file IDs to state
- [ ] **1-D-4** **PREFLIGHT**: health-check Ollama, Qdrant, sandbox; emit SSE `state_change`; hard-fail if any are down
- [ ] **1-D-5** **ROUTE**: call `ModelRouter`; emit `router_decision` SSE; trigger model swap
- [ ] **1-D-6** **PLAN**: invoke selected Ollama model via LangChain `ChatOllama` with tool schemas; receive ordered tool-call plan; store in `state.plan`
- [ ] **1-D-7** **ACT**: pop next tool from plan; validate against allowlist; emit `tool_call` SSE with sanitized args; execute via LangChain tool wrapper
- [ ] **1-D-8** **OBSERVE**: receive tool result; emit `tool_result` SSE; append to `state.observations`; decide: next tool / retry / escalate
- [ ] **1-D-9** **VERIFY**: check deliverable (call `verify_docx` or inspect test output); if missing citations or failed — re-enter PLAN once
- [ ] **1-D-10** **AWAIT_APPROVAL**: persist run state to Postgres; pause graph (LangGraph `interrupt()` or checkpoint); resume on `POST /api/runs/{id}/approval`
- [ ] **1-D-11** **DELIVER**: finalize artifact, hash it, write final audit event, emit `run_complete` SSE
- [ ] **1-D-12** Guards: max 8 tool cycles (`iteration_count`); 10-min wall-clock timeout; unsupported tool → log + skip

---

## 1-E · Episodic Memory (LangChain + Postgres)
**Deps:** 1-A (schema), 1-D | **Est: 1 h**

> Episodic memory lets the agent reference earlier steps within the same run (e.g. OCR output when writing the DOCX). Not cross-run memory — that is Phase 3.

- [ ] **1-E-1** `PostgresChatMessageHistory` (LangChain community) keyed by `run_id` — stores all agent messages for the current run
- [ ] **1-E-2** `ConversationSummaryMemory` wraps the history; summarises older messages when context window fills up; summary stored back in Postgres
- [ ] **1-E-3** Memory is passed as context in every `PLAN` and `OBSERVE` node invocation so the agent never re-reads already-processed tool outputs from scratch
- [ ] **1-E-4** Memory is scoped strictly to one `run_id`; no cross-run leakage

---

## 1-F · Audit Log
**Deps:** 1-A (schema) | **Est: 45 min**

- [ ] **1-F-1** `audit_events` append-only (no UPDATE/DELETE); fields: `run_id`, `timestamp`, `event_type`, `model_id`, `tool_name`, `sanitized_args`, `result_hash`, `approval_decision`, `blocked_tool_attempt`
- [ ] **1-F-2** Every state transition, tool call, approval, and blocked attempt writes a row
- [ ] **1-F-3** `GET /api/sovereignty/status` returns 20 most recent events in `audit_tail`

---

## 1-G · OCR + Vision Pipeline
**Deps:** 1-A (volumes), Tesseract in `worker` image, 0-B-3 | **Est: 2 h**

- [ ] **1-G-1** `extract_pdf_pages` tool: render PDF pages to PNG @ 150 dpi (PyMuPDF / pdf2image); store in `{run_workspace}/pages/`; return `[{page_number, image_path}]`
- [ ] **1-G-2** `run_ocr` tool: call `pytesseract.image_to_data()` on each page; return `{page_number, text, confidence}`
- [ ] **1-G-3** `inspect_image` tool: send page PNG to `qwen2.5vl:7b` via `ChatOllama` with image; return `{description, anomalies_found}`
- [ ] **1-G-4** Low OCR confidence (<60%) on a region → auto-trigger `inspect_image` on that crop; merge both outputs
- [ ] **1-G-5** All chunks carry `{source_file, page_number}` metadata through to Qdrant

---

## 1-H · Tool Registry + Policy
**Deps:** 1-A | **Est: 1 h**

- [ ] **1-H-1** All tools are LangChain `@tool` decorated functions with Pydantic input schemas
- [ ] **1-H-2** Fixed allowlist — any tool name not in this list is rejected and logged:
  `extract_pdf_pages`, `run_ocr`, `inspect_image`, `search_knowledge`, `read_source_excerpt`,
  `read_spreadsheet`, `analyze_spreadsheet`, `create_approval_docx`, `write_code_file`,
  `run_code_tests`, `verify_docx`, `list_run_artifacts`, `request_human_approval`
  *(PPTX/XLSX gen: stubs only, return `{status: "roadmap"}` — not wired to demo flow)*
- [ ] **1-H-3** All tool path args validated as subdirectory of `{run_workspace}`; any `..`, `/etc`, or URL → reject + audit log
- [ ] **1-H-4** No tool exposes shell exec, Docker socket, URL fetch, or unrestricted paths

---

## 1-I · Local RAG Pipeline
**Deps:** 1-A (Qdrant), 1-G | **Est: 2 h**

- [ ] **1-I-1** Ingestion: file hash → PDF text extract → page OCR where needed → chunk by heading/page → BGE-M3 embeddings (via `FlagEmbedding` locally) → BM25 update → Qdrant upsert with `{chunk_id, source_file, page_number, text, embedding}`
- [ ] **1-I-2** `search_knowledge` tool: dense (BGE-M3) + BM25 hybrid → top-12 → rerank with `bge-reranker-v2-m3` locally → return top-5 with `{score, source_file, page_number, excerpt}`
- [ ] **1-I-3** `read_source_excerpt` tool: given `chunk_id`, return full chunk text
- [ ] **1-I-4** DOCX generation must include ≥ 2 source citations; `VERIFY` fails without them

---

## 1-J · Approval-Note DOCX Generator
**Deps:** 1-H, 1-I | **Est: 1.5 h**

- [ ] **1-J-1** `create_approval_docx` tool: `python-docx`; mandatory sections: **Purpose**, **Source Report Metadata**, **Extracted Findings Table**, **Applicable SOP Clauses** (with page citations), **Recommended Action**, **Risk Notice** ("Requires authorized engineer approval"), **Approval / Signature Placeholders**
- [ ] **1-J-2** After generation, `verify_docx` runs automatically; missing heading → agent retries once
- [ ] **1-J-3** `verify_docx`: file exists, size > 5 KB, all headings present, ≥ 2 citations, parseable by `python-docx`

---

## 1-K · Human Approve / Reject Flow
**Deps:** 1-C-6, 1-D (AWAIT_APPROVAL), 1-F | **Est: 45 min**

- [ ] **1-K-1** Run enters `AWAIT_APPROVAL` → SSE `awaiting_approval` event → Postgres status `awaiting_approval`
- [ ] **1-K-2** `POST /api/runs/{id}/approval` writes decision row + two audit rows (decision + artifact hash)
- [ ] **1-K-3** LangGraph graph resumes from checkpoint on approval; transitions to `DELIVER` (approve) or re-enters `PLAN` with rejection note (reject, once only)
- [ ] **1-K-4** Agent cannot self-approve — no code path in the graph calls the approval endpoint

---

## 1-L · Spreadsheet Tool
**Deps:** 1-H | **Est: 1 h**

- [ ] **1-L-1** `read_spreadsheet`: load `.xlsx` with `openpyxl`/`pandas`; return `{sheet_names, columns, row_count, sample_rows[5]}`
- [ ] **1-L-2** `analyze_spreadsheet`: given a natural-language question + spreadsheet summary, answer with matched rows/values
- [ ] **1-L-3** Run-scoped path validation; file never executed

---

## 1-M · Code Generation + Sandbox + Repair
**Deps:** 1-H, 0-F | **Est: 2 h**

- [ ] **1-M-1** `write_code_file`: write agent code to `{run_workspace}/code/{filename}`; allowlisted extensions `.py`, `.sh`
- [ ] **1-M-2** `run_code_tests`: send code to the pre-warmed `sandbox` service; capture stdout/stderr/exit; return structured result
- [ ] **1-M-3** Repair loop: if non-zero exit, feed stderr back to `PLAN` → regenerate → test once more. Max one repair.
- [ ] **1-M-4** Both sandbox runs visible in SSE trace and audit log

---

## 1-N · Sovereignty Console (Backend)
**Deps:** 1-C-7, 1-F | **Est: 45 min**

- [ ] **1-N-1** `GET /api/sovereignty/status` returns: `model_endpoints[]`, `internal_network: bool`, `egress_blocked: bool`, `offline_capable: bool`, `sandbox_network_mode: "none"`, `audit_tail[20]`
- [ ] **1-N-2** Live Docker network inspect on each request → `internal_network` flag
- [ ] **1-N-3** Egress check: TCP connect attempt to `8.8.8.8:443`, 2 s timeout → sets `egress_blocked`

---

## 1-O · Frontend UI
**Deps:** 1-C (all endpoints), 1-D (SSE), 1-K (approve), 1-N | **Est: 4 h**

### Layout
- [ ] **1-O-1** **Left panel:** task prompt textarea, file upload (drag-and-drop), knowledge-base SOP selector
- [ ] **1-O-2** **Center panel:** streaming agent trace — each event fades in (opacity 0→1, translateY 6px→0, 150 ms); current state badge
- [ ] **1-O-3** **Right panel:** router decision card (first, before any agent step) → evidence citations → artifact download → **Approve / Send Back** (visible only in `AWAIT_APPROVAL`) → Sovereignty Console tab

### Design
- [ ] **1-O-4** Palette: `#0f1117` bg, `#1e2130` surface, `#3b82f6` accent, `#f8fafc` text — max 3 colors
- [ ] **1-O-5** Typography: Inter (self-hosted in Docker image — no Google CDN), weights 400 + 600 only
- [ ] **1-O-6** Glassmorphism on three main panels only: `backdrop-filter: blur(12px)`, `background: rgba(30,33,48,0.7)`, `border: 1px solid rgba(255,255,255,0.08)`
- [ ] **1-O-7** Approve button pulses once when run enters `AWAIT_APPROVAL`; no other decorative animation
- [ ] **1-O-8** Model selector is display-only during a run
- [ ] **1-O-9** All interactive elements have unique `id` attributes
- [ ] **1-O-10** Sovereignty Console tab: model endpoints, network badge, sandbox badge, offline badge, scrollable audit trace; auto-refresh every 5 s

---

## 1-P · Synthetic Fixture Pack
**Deps:** None (parallel with 1-A) | **Est: 1.5 h**

- [ ] **1-P-1** `fixtures/inspection_report.pdf`: 3–5-page synthetic scanned corrosion report, embedded photo, handwritten annotation, labelled "SYNTHETIC FIXTURE"
- [ ] **1-P-2** `fixtures/corrosion_sop.pdf`: SOP with threshold ("corrosion depth > 2 mm → escalate") and escalation steps
- [ ] **1-P-3** `fixtures/pid_drawing.png`: simple P&ID-like schematic, labelled synthetic
- [ ] **1-P-4** `fixtures/readings_log.xlsx`: ≥ 3 sheets; column D has readings where ≥ 2 rows exceed a threshold
- [ ] **1-P-5** `fixtures/golden_findings.json`: expected OCR findings, SOP citation page numbers, required DOCX headings — the test oracle
- [ ] **1-P-6** `fixtures/coding_fixture.py`: function with known off-by-one bug + test suite that fails first, passes after one repair

---

## 1-Q · End-to-End Demo Tests
**Deps:** All of 1-A–1-P | **Est: 1.5 h**

- [ ] **1-Q-1** **Hero run:** upload `inspection_report.pdf` + ingest `corrosion_sop.pdf` → goal "Draft approval note" → assert: multimodal routing, OCR ≥ 20 words, ≥ 2 SOP citations in DOCX, DOCX valid, run pauses at `AWAIT_APPROVAL`, approval recorded, run completes in < 4 min
- [ ] **1-Q-2** **Coding run:** submit `coding_fixture.py` → assert: coding routing, first sandbox fails, agent repairs, second passes, both in audit log
- [ ] **1-Q-3** **Spreadsheet run:** upload `readings_log.xlsx` → ask threshold question → assert: spreadsheet-analysis routing, correct rows identified
- [ ] **1-Q-4** **Offline run:** disable internet → re-run 1-Q-1 → assert: no outbound TCP, sovereignty status shows `egress_blocked: true`

---

## Phase 1 Sign-Off

| Component | Status |
|-----------|--------|
| 1-A Scaffold + Compose | ⬜ |
| 1-B Model registry + router | ⬜ |
| 1-C Core API + SSE | ⬜ |
| 1-D LangGraph agent | ⬜ |
| 1-E Episodic memory | ⬜ |
| 1-F Audit log | ⬜ |
| 1-G OCR + vision | ⬜ |
| 1-H Tool registry | ⬜ |
| 1-I Local RAG | ⬜ |
| 1-J DOCX generator | ⬜ |
| 1-K Approve/reject | ⬜ |
| 1-L Spreadsheet tool | ⬜ |
| 1-M Code sandbox + repair | ⬜ |
| 1-N Sovereignty Console | ⬜ |
| 1-O Frontend UI | ⬜ |
| 1-P Fixture pack | ⬜ |
| 1-Q E2E tests | ⬜ |

**Total est: 24–28 h focused build time**
