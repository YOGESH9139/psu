# Sovereign AI Workbench — Final Hackathon MVP Plan (SIH26117 / MRPL)

## Summary

Build a Docker-based, fully local "private Claude + Codex" workbench for a single 12–16 GB GPU workstation. The MVP proves every core PS requirement end-to-end:

| PS requirement | MVP proof |
|---|---|
| Automatic model selection | Visible router selects a coding model or multimodal document model automatically. |
| Agentic execution | A bounded plan → tool-use → observe → verify loop, not a one-shot answer. |
| Multimodal understanding | OCR plus VLM analysis of a scanned inspection-report fixture and equipment/drawing image. |
| Local RAG | Findings are compared against locally indexed synthetic SOPs, with page citations. |
| Sovereignty | Internal-only Docker networking, no cloud credentials/tools, offline run, and visible audit/egress evidence. |
| Human-in-the-loop | Explicit approve/reject action in the UI before a recommendation is treated as final. |
| Spreadsheet analysis | Agent can read and answer questions on an existing XLSX, not just generate one. |

The hero workflow is: **scanned inspection report → OCR + VLM → local SOP retrieval → findings comparison → approval-note DOCX → human approve/reject → verify**. A second compact workflow demonstrates: **coding prompt → code generation → isolated execution → tests → repair if needed**.

## Architecture and Interfaces

```text
Browser UI (React)
       │ localhost only
FastAPI API + SSE event stream
       │
Agent Runner ── Model Router ── Local Model Gateway ── Ollama / vLLM
       │                │
Typed Tool Registry     ├─ Qwen3 8B: planning, coding, tool calling
       │                └─ Qwen3-VL 8B: documents/images
       ├─ OCR + PDF/image extraction
       ├─ Local RAG: BGE-M3 + BM25 + reranker + Qdrant
       ├─ Spreadsheet reader (pandas/openpyxl)
       ├─ Artifact writers: DOCX, XLSX, PPTX
       └─ Docker-isolated Python sandbox

PostgreSQL: runs, audit events, metadata, approval decisions
Local volumes: uploads, knowledge base, run workspaces, artifacts, model files
```

- Use Docker Compose with `frontend`, `api`, `worker`, `postgres`, `redis`, `qdrant`, and a local model-server service. All services join an `internal: true` Docker network; Docker documents that this removes a default route for external connectivity. [Docker networking documentation](https://docs.docker.com/compose/how-tos/networking/)
- Use React + TypeScript + Vite for the browser interface; FastAPI + Pydantic for the backend; PostgreSQL for durable metadata/audit; Redis only for local task jobs; Qdrant for vector search.
- Implement a model abstraction, not model-specific business logic. `models.yaml` defines each local model's endpoint, capabilities, context limit, preferred tasks, GPU tier, health status, and preload behavior.

- Default portable model profile:
  - `Qwen3-8B`, Q4 quantized: planning, code, tool calls, summarization.
  - `Qwen3-VL-8B`, Q4 quantized: page images, photographs, drawings, visual cross-checking.
  - `BAAI/bge-m3`: local embeddings; BM25 for lexical retrieval; local reranker for the final retrieved passages.

  Qwen3 has documented function-calling support through OpenAI-compatible serving; the 8B Q4 profile is suitable for mid-range VRAM. [Qwen function-calling documentation](https://github.com/QwenLM/Qwen3/blob/main/docs/source/framework/function_call.md) BGE-M3 supports multilingual, dense, sparse, and multi-vector retrieval, and its authors recommend hybrid retrieval plus reranking. [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3)

- Router policy is deterministic and visible:
  - Files containing pages/images, OCR requests, inspection analysis, drawing/photo review → `multimodal-document`.
  - Code creation/debugging, file extensions such as `.py`/`.js`, explicit tests → `coding`.
  - Existing spreadsheet uploaded for analysis → `spreadsheet-analysis` (routes to general-reasoning model + spreadsheet tool).
  - Plain approval-note reasoning and general chat → `general-reasoning`.
  - Router returns `{modelId, taskClass, confidence, matchedSignals, fallback}` and the UI displays it before agent execution.
  - Only one large model is resident at a time on 12–16 GB GPUs; the router unloads the prior model before loading the selected one.

- Public API:
  - `POST /api/files` — local upload and MIME validation.
  - `POST /api/knowledge/ingest` — ingest local SOP/manual files.
  - `POST /api/runs` — create a task with goal and input file IDs.
  - `GET /api/runs/{id}` and `GET /api/runs/{id}/events` — status and live trace.
  - `GET /api/runs/{id}/artifacts` — signed local artifact download.
  - `POST /api/runs/{id}/approval` — record human approve/reject decision, writes an audit event.
  - `GET /api/sovereignty/status` — active services, model endpoints, egress-block state, and latest audit events.

## Agent, Tools, RAG, and Deliverables

- Implement the agent as an explicit typed state machine rather than relying on a framework label:

  `INTAKE → PREFLIGHT → ROUTE → PLAN → ACT → OBSERVE → VERIFY → AWAIT_APPROVAL → DELIVER`

  Each run has a maximum of 8 tool cycles and 10 minutes. Failed tools feed structured observations back to the agent; repeated failures, unsupported tools, or low-confidence evidence stop the run and request human review. Any run producing a safety- or approval-relevant recommendation must pause at `AWAIT_APPROVAL` until a human records a decision via `POST /api/runs/{id}/approval` — the run cannot self-finalize.

- Expose only typed, allowlisted tools:
  - `extract_pdf_pages`, `run_ocr`, `inspect_image`
  - `search_knowledge`, `read_source_excerpt`
  - `read_spreadsheet`, `analyze_spreadsheet`
  - `create_approval_docx`, `create_calculation_xlsx`, `create_presentation_pptx`
  - `write_code_file`, `run_code_tests`
  - `verify_docx`, `list_run_artifacts`
  - `request_human_approval`

  Do not expose arbitrary host shell execution, browser access, URL fetching, Docker socket access, or unrestricted filesystem paths.

- Ingestion pipeline: file hash → malware/type check → PDF text extraction → rendered-page OCR where needed → preserve page/crop references → chunk by heading/page → local embeddings + BM25 index → Qdrant metadata. Retrieval returns the top 12 hybrid candidates, reranks to 5, and requires source/page citations in final approval notes.

- The approval-note template must contain: purpose, source-report metadata, extracted findings table, applicable SOP clauses with citations, recommended action, risk/human-review notice, and approval/signature placeholders (bound to the actual human decision recorded via the approval endpoint). Verify the generated DOCX by reopening it and checking mandatory headings, citations, and file existence.

- `read_spreadsheet` / `analyze_spreadsheet`: load an uploaded XLSX with pandas/openpyxl, expose sheet/column summary to the agent, and answer natural-language questions about the data (e.g. "which readings exceed the threshold in column D"). This satisfies the PS's spreadsheet-analysis tool requirement, distinct from spreadsheet generation.

- Code execution runs in a fresh Docker container with `network_mode: none`, read-only root filesystem, dropped Linux capabilities, CPU/memory/PID limits, a 60-second timeout, and only the current run workspace mounted. The agent may repair code once after observing test failure.

## Sovereignty, Security, and Audit

- Pre-stage all container images, Python wheels, model weights, OCR models, and demo data before the venue. Run the demo with Internet disabled; no runtime downloads, analytics, CDN assets, cloud API keys, or remote embedding/OCR calls are permitted.
- Enforce an internal-only Docker network and bind the browser/API solely to `127.0.0.1`. The model gateway allowlists only local container service names. All tool inputs use run-scoped paths and are validated with Pydantic.
- Treat uploaded content as untrusted: document text may inform an answer but cannot alter tool permissions, execute commands, or override the fixed system policy.
- Store append-only audit events: run ID, user action, router decision, selected model, tool name, sanitized arguments, duration, result hash, artifact hash, source citations, approval decision, blocked-tool attempts, and egress-check results. Preserve raw sensitive content only in the approved local run workspace, not in UI telemetry.
- Add a "Sovereignty Console" tab showing: internal model endpoints, no external integrations configured, Docker network inspection result, sandbox `network=none`, offline health check, and the live audit trace. This is the central differentiator from teams that merely claim local AI.

## Exact MVP, Demo Pack, and UX

- Build a synthetic, clearly labelled industrial fixture pack:
  - 3–5-page scanned corrosion/inspection report with one embedded equipment photograph and handwritten annotation.
  - Local SOP defining an inspection threshold and escalation process.
  - Small non-safety-critical P&ID-like drawing used only for visual identification.
  - A sample XLSX of readings/logs for the spreadsheet-analysis tool.
  - Golden findings and expected citations for evaluation.

  Never portray the VLM as a certified engineering or safety decision-maker; every generated recommendation includes "requires authorized engineer approval," and that requirement is enforced by the `AWAIT_APPROVAL` state, not just stated in text.

- Interface:
  - Left: task prompt, local file upload, knowledge-base selector.
  - Center: agent plan and streaming tool timeline.
  - Right: router decision, cited evidence, artifact preview/download, **Approve / Send Back** action, and audit/sovereignty panel.
  - The model selector is display-only during the judged workflow so automatic routing is unambiguous.

- Hero demonstration:
  1. Start with Internet disabled and show the Sovereignty Console.
  2. Upload the scanned report and submit "Draft an approval note using the corrosion SOP."
  3. Show routing to the multimodal model, OCR, image review, SOP retrieval, and evidence citations.
  4. Open the generated DOCX and show its findings table and source references.
  5. Show the run paused at `AWAIT_APPROVAL`; click **Approve**, show the audit event and finalized artifact.
  6. Submit a small internal utility coding request.
  7. Show routing to the coding model, sandbox test failure/success trace, repaired code, and verified test output.
  8. Upload the sample XLSX and ask a data question, showing the spreadsheet-analysis tool in action.
  9. End on the audit log and offline network proof.

- Deliberately exclude in the hackathon MVP: enterprise SSO, multi-user collaboration, distributed GPU scheduling, live internal-system connectors, automatic (non-human) approval submission, and claims of engineering certification. PPTX/XLSX **generation** writers are included as artifact adapters but are shown as roadmap, not a mandatory demo flow — only DOCX generation and verified code execution are mandatory.

## Test Plan and Acceptance Criteria

- Unit tests:
  - Router correctly classifies document, image, code, and spreadsheet-analysis requests.
  - Tool schemas reject host paths, URLs, unsupported file types, and malformed arguments.
  - Chunk/page metadata remains intact through ingestion and retrieval.
  - DOCX/XLSX/PPTX generators produce readable files with required fields.
  - `read_spreadsheet` correctly parses the sample fixture and answers a known query.

- Integration tests:
  - Fixed fixture produces all golden findings, at least two correct SOP citations, and a valid approval-note DOCX.
  - Run correctly halts at `AWAIT_APPROVAL` and only finalizes after a recorded human decision.
  - Coding fixture intentionally fails first, then passes after one agent repair cycle.
  - Sandbox cannot resolve or reach an external address and stops at timeout/resource limits.
  - Docker network reports internal-only; the complete fixture workflow succeeds with network disabled.

- Demo acceptance thresholds:
  - One complete hero run in under 4 minutes on the target GPU.
  - Visible automatic routing for at least three task types (document, code, spreadsheet).
  - Every substantive approval-note recommendation cites local source material.
  - No outbound request or cloud credential appears in logs.
  - Generated DOCX opens successfully; code tests pass in the isolated sandbox; approval action is recorded in the audit log.

## Delivery Sequence

1. **Phase 0 — Offline package:** lock container/image digests, download model/OCR artifacts, checksum them, and validate the full stack without Internet.
2. **Phase 1 — Platform spine:** Compose stack, model registry/router, upload/storage, Qdrant ingestion, SSE trace, and sovereignty/audit schema.
3. **Phase 2 — Hero agent:** OCR/VLM extraction, hybrid RAG, approval-note template, `AWAIT_APPROVAL` + approve/reject endpoint, artifact verification, and the synthetic fixture pack.
4. **Phase 3 — Coding proof + spreadsheet tool:** sandbox runner, test/repair loop, `read_spreadsheet`/`analyze_spreadsheet` tool, tool-policy hardening, and route evidence.
5. **Phase 4 — Demo hardening:** offline rehearsal, golden end-to-end tests, latency tuning, judge script, and failure fallbacks.

## Team Split

- Docker/infra + model registry/router — build first, everyone else is blocked on this.
- Agent state machine + tool orchestration (1–2 people) — the core loop.
- RAG/OCR/vision pipeline — ingestion, retrieval, citations.
- Sandbox + coding-agent workflow — isolated execution, test/repair loop.
- Frontend — trace view, Sovereignty Console, Approve/Send Back action.
- Synthetic fixture pack + demo script + pitch deck — don't let this get squeezed to the last hour; it's what makes the demo feel real.

## Assumptions and Defaults

- The current workspace is empty; the prototype begins as a clean Docker Compose application.
- Target hardware is a 12–16 GB NVIDIA GPU with Docker Desktop/WSL GPU support. A 24 GB profile upgrades the general model to 14B; a 48 GB profile may use a stronger 32B-class model without changing the router or API.
- Synthetic industrial data is the reliable baseline; approved redacted documents can be added through the same ingestion path.
- The product is an internal decision-support workbench, never an autonomous approver or safety authority — enforced structurally via `AWAIT_APPROVAL`, not only stated in copy.