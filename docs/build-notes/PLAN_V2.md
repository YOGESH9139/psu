# Sovereign AI Workbench — V2 Plan

**Problem statement:** SIH26117. A self-hosted, air-gapped AI workbench that works the way Claude or Codex does, for data that can never leave the premises.

**What this doc is:** the complete target, every feature traced to a line of the problem statement, plus a build order that's honest about a couple of days on an 8 GB laptop GPU. Nothing here has been executed yet.

---

## 0. Where we stand

| Area | Built and working | Gap against the PS |
|---|---|---|
| Air-gap | Internal Docker network, measured egress probes in the worker and sandbox, airgap overlay | No **visible network monitor**. The PS asks for one explicitly. Right now we have probes, not a monitor. |
| Multi-model | Registry (`models.yaml`), deterministic router, VRAM hot-swap | Only 2 models. Coding and summarising go to the *same* model, which is the exact example the PS says should be "handled differently". No clean path to add a model. |
| Agent | LangGraph state machine, tool allowlist, verify/repair, human approval gate | Plans are fixed per task class, so the LLM doesn't actually plan. Single turn, no follow-ups. No general file read/write tool. |
| Multimodal | Tesseract OCR, Qwen2.5-VL page inspection | Slow (~5 min). No drawing understanding. No handwriting-specific path. Findings aren't linked to *where* on the page they came from. |
| Deliverables | Approval-note DOCX with preview | PPT and Excel are stubs. No calculations with steps shown. |
| Knowledge base | Hybrid dense + BM25 retrieval with RRF, page citations | Manual upload only. No folder or email connector, no reranker, and clicking a citation can't open the source. |
| Code | Isolated sandbox with pytest, verify/repair loop | Python tests only. No plots, data files or run output shown as artifacts. |
| UI | React workbench: run panel, results as data, approval dialog, document viewer | No conversation, no history, no PPT/XLSX/code previews, no network view. |

The spine is sound. V2 is about closing the PS gaps and adding the few features that make this read as a *product* rather than a pipeline.

---

## 1. Requirement traceability

Every PS clause, what satisfies it, and how a judge *sees* it.

| # | PS says | V2 feature | Proof in the demo |
|---|---|---|---|
| R1 | "self-hosted, air gapped … nothing leaves the premises" | Internal-only networks, DNS sinkhole, browser CSP, pre-staged weights | Pull the network cable mid-demo and everything keeps working |
| R2 | "not locked to one model … multiple open weight models at once" | Model registry v2 with runtime adapters (Ollama, llama.cpp, vLLM/OpenAI-compatible) | Model Garden page listing 3–4 live models with their capabilities |
| R3 | "automatically pick the right one … coding handled differently from a document summary" | Router v2: rules → capability match → tiny classifier model as tie-breaker | The routing card shows *why* each request went to a different model |
| R4 | "new open weight models should be addable later without redesigning" | Model Garden: register a model, auto-benchmark it, router starts using it when it wins | Add a model live; the router picks it up with no code change |
| R5 | "plan out multi step work … iterate instead of answering once" | LLM planner with playbooks, visible editable plan, observe → replan loop, verifiers | The plan appears first, a step fails, the agent re-plans and recovers |
| R6 | "file read and write, code execution in a sandbox, spreadsheet work, internal document search" | Full tool catalog (§3.3) | Each tool call visible in the run panel, expandable |
| R7 | "scanned PDFs, handwritten notes, engineering drawings, photographs … on device OCR and vision" | Page triage → OCR / handwriting / drawing / photo paths, with visual grounding | Findings drawn as boxes on the actual scanned page |
| R8 | "approval notes, PPT/Word/Excel files, working code, calculations with steps shown" | Deliverables engine plus Artifact Studio | Live preview of the DOCX page, PPT slides, XLSX grid and code + test output |
| R9 | "ground itself in manuals, SOPs and past correspondence … local knowledge base connector" | KB connector for watched folders, `.eml`/`.msg` mail, PDFs and DOCX, with a reranker | Click a citation and the source PDF opens at the highlighted passage |
| R10 | "working local deployment … mid range GPU (use a smaller model…)" | Hardware profiles: laptop 8 GB, workstation 24 GB, server 80 GB+ | One `PROFILE=` switch, same code |
| R11 | "model auto selection across at least two different task types" | 4 task classes → 3+ models | Covered by R3 |
| R12 | "read a scanned inspection report, pull out key findings and draft an approval note as a Word file" | Hero flow (exists, gets faster and grounded) | End to end in < 90 s |
| R13 | "coding task run and verified in a sandbox" | Coder model + sandbox + test/repair loop | Tests fail first, get repaired, then pass |
| R14 | "multimodal task involving image or scanned document understanding" | Drawing digitizer + photo defect review | P&ID → equipment list in Excel |
| R15 | "through logs or a visible network monitor, that no external calls are made at any point" | **Live Sovereignty Map**, DNS query log, tamper-evident audit chain, per-run sovereignty report | Every connection drawn live; an external attempt flashes red and is blocked |

---

## 2. Target architecture

```
                 ┌──────────────────────────── Browser (CSP: 'self' only) ────────────────────────────┐
                 │  Workbench · Artifact Studio · Sovereignty Map · Model Garden · Knowledge · Evals   │
                 └───────────────────────────────────────┬─────────────────────────────────────────────┘
                                                         │ 127.0.0.1 only
┌──────────────────────────────────── API gateway (FastAPI) ────────────────────────────────────────────┐
│  sessions/threads · files · runs · SSE · approvals · artifacts+previews · KB · models · netwatch feed   │
└──────┬──────────────────────────┬────────────────────────────┬──────────────────────────┬─────────────┘
       │ job queue (Redis)        │                            │                          │
┌──────▼──────────────── Agent Runtime (worker) ─────────┐     │                          │
│ Router v2 ─► Planner (LLM + playbooks) ─► Executor      │     │                          │
│   ▲                          │           │              │     │                          │
│   │   Observer/Replanner ◄───┘      Tool Gateway ───────┼─────┼── allowlist · schemas ·  │
│   │   Verifiers (docx/xlsx/pptx/code/calc/citations)    │     │   path policy · budgets  │
│   └── Episodic memory · thread context                  │     │                          │
└──────┬───────────────┬──────────────┬──────────────┬────┘     │                          │
       │               │              │              │          │                          │
┌──────▼─────┐ ┌───────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐ ┌─▼──────────┐ ┌─────────────▼──────┐
│ Model      │ │ Vision/OCR   │ │ Knowledge  │ │ Deliverable│ │ Sandbox    │ │ Netwatch           │
│ Gateway    │ │ service      │ │ service    │ │ engine     │ │ (net=none) │ │ conntrack + DNS    │
│ adapters:  │ │ triage, OCR, │ │ connectors,│ │ docx/pptx/ │ │ py/pytest, │ │ sinkhole + egress  │
│ ollama,    │ │ handwriting, │ │ chunk,     │ │ xlsx/calc, │ │ plots,     │ │ firewall log       │
│ llama.cpp, │ │ drawings,    │ │ hybrid +   │ │ previews   │ │ data files │ │ → live topology    │
│ openai-api │ │ grounding    │ │ rerank     │ │            │ │            │ │                    │
└──────┬─────┘ └──────────────┘ └─────┬──────┘ └────────────┘ └────────────┘ └────────────────────┘
       │                              │
   GPU models                  Qdrant · Postgres (runs, audit hash-chain, KB metadata) · MinIO-free local volumes
```

**Design rules that carry through everything:**

1. **Models are data, not code.** Anything model-specific lives in `models.yaml` and adapters. Business logic only ever asks for a *capability*.
2. **Every claim is measured.** The sovereignty status, router confidence, verifier results and eval scores come from something that actually ran.
3. **The LLM proposes and code disposes.** Filters, calculations, citations checks and file validation are deterministic code. The model plans, extracts and writes prose.
4. **Nothing is final without a human** when the output is safety- or approval-relevant.
5. **One hardware profile switch.** Laptop and server run the same code with different model tiers.

---

## 3. Subsystems

### 3.1 Model layer (R2, R3, R4, R10, R11)

**Registry v2 (`models.yaml`)**, one card per model:

```yaml
- id: qwen25-coder-7b
  runtime: ollama              # ollama | llamacpp | openai_compat
  ref: qwen2.5-coder:7b
  capabilities: [code_gen, code_repair, tool_calling]
  modalities: [text]
  context: 32768
  vram_gb: 5.2
  profile: [laptop, workstation]
  quality: {coding: 0.78, summarise: 0.55}   # written by the benchmark, not by hand
  keep_alive: 5m
```

**Runtime adapters.** One interface (`chat`, `chat_json`, `vision`, `health`, `load`, `unload`) with three implementations:
- Ollama (today)
- llama.cpp server
- Any OpenAI-compatible endpoint (vLLM, TGI, LM Studio), which is how a 120B server deployment slots in

**Router v2**, three stages, every stage visible in the UI:

1. **Rules.** File type, extension, explicit keywords. This is today's router, still deterministic.
2. **Capability match.** Task class → required capabilities → pick the highest-`quality` model the current profile can hold.
3. **Tie-breaker.** Only when rule confidence < 0.7: a tiny classifier model (Qwen3-1.7B or 0.6B, **on CPU**, ~1 GB RAM) labels the intent. It's cheap and never touches the GPU.

Output stays `{task_class, model_id, confidence, signals, stage_that_decided, alternatives}`.

**Task classes → models (laptop profile):**

| Task class | Model | Why it's separate |
|---|---|---|
| `coding` | Qwen2.5-Coder 7B | The PS's own example: code is handled differently |
| `document-summary` / `general` | Qwen3 8B | Reasoning and prose |
| `multimodal-document` | Qwen2.5-VL 7B | Pages, drawings, photos |
| `spreadsheet` / `calculation` | Qwen3 8B + deterministic engines | The model plans, code computes |
| router tie-break | Qwen3 1.7B (CPU) | Tiny, always resident |

**VRAM scheduler.** Knows each model's `vram_gb` and the card's budget. Keeps the current model resident, evicts only what's loaded, and **batches same-model steps together** in a plan to avoid swaps.

**Model Garden** (the R4 feature):
1. Operator registers a model from a local GGUF path or an Ollama tag already present on disk (air-gapped, so nothing is pulled at runtime).
2. The system runs the **eval pack** (§3.12) for that model's declared capabilities.
3. Scores get written into its card. The router starts preferring it wherever it wins.
4. The UI shows a leaderboard per task class, and every change is logged.

### 3.2 Agent core v2 (R5, R6)

**Loop:** `INTAKE → ROUTE → PLAN → [PLAN REVIEW] → ACT ⇄ OBSERVE → (REPLAN) → VERIFY → AWAIT_APPROVAL → DELIVER`

**Planner = LLM + playbooks.** Today the plan is hard-coded per task class. V2:
- **Playbooks** are the current skeletons, kept as reliable, named templates (`inspection_to_approval_note`, `spreadsheet_question`, `code_fix_and_test`, `drawing_to_equipment_list`, `board_deck_from_docs`, `engineering_calc`).
- The planner LLM receives the goal, attached files, tool catalog and playbook list. It outputs a JSON plan, either "use playbook X with these modifications" or a free plan.
- The plan is **schema-validated**. An invalid plan falls back to the best-matching playbook. The demo can't be broken by a bad plan.

**Plan review (new).** The plan is shown *before* execution as editable cards: reorder, remove, add a step, or "go". It has a skip-review toggle and an auto-go timer. This moves the human in the loop from the end to the start, which is exactly what an engineer would want.

**Observer / replanner.** After each tool result it decides: continue, retry with changed arguments, insert steps, or escalate to the human. It's bounded by the existing guards (tool budget, wall clock, one replan).

**Verifiers**, one per deliverable type, all deterministic:
- DOCX: mandatory sections, citations resolve to real KB chunks
- XLSX: formulas recalculate with no `#REF!`/`#DIV/0!`
- PPTX: slide count, no overflow, citations on data slides
- Code: tests pass in the sandbox
- Calc: units consistent, recomputation matches
- Findings: every finding has an evidence region or a quote

**Conversation threads.** Follow-ups work on the same workspace: "now make this a 5-slide deck for the board", "change the threshold to 80". Thread memory = the run's episodic memory (built) plus prior artifacts. History is stored locally in Postgres with a clear-history control.

**Prompt-injection guard.** Document text is always passed as *data* inside delimited blocks. Tool permissions come from the allowlist, never from content. There's a test fixture with a malicious "ignore previous instructions" PDF, and the audit log shows it had no effect.

### 3.3 Tool catalog (R6)

| Tool | Status | Notes |
|---|---|---|
| `read_file`, `write_file`, `list_files`, `diff_files` | **new** | The PS names "file read and write". Workspace-scoped, text, CSV and JSON |
| `extract_pdf_pages`, `run_ocr`, `inspect_image` | exists | `inspect_image` gains region/bbox output |
| `triage_page` | **new** | Classifies each page: typed / scanned / handwritten / drawing / photo / table |
| `read_handwriting` | **new** | VLM transcription of handwritten regions with confidence |
| `digitize_drawing` | **new** | P&ID / drawing → tags, equipment, lines as a table plus boxes |
| `review_photo` | **new** | Defect description and location on photographs |
| `search_knowledge`, `read_source_excerpt` | exists | Adds reranker, metadata filters, `open_source_page` |
| `read_spreadsheet`, `analyze_spreadsheet` | exists | Adds pivot, group-by, chart |
| `run_calculation` | **new** | Calculation engine (§3.7) |
| `create_approval_docx`, `verify_docx` | exists | Adds template library and revise-in-place |
| `create_xlsx`, `verify_xlsx` | **new** (stub today) | Real formulas, not pasted values |
| `create_pptx`, `verify_pptx` | **new** (stub today) | Corporate template, charts, speaker notes |
| `write_code_file`, `run_code_tests` | exists | Adds `run_script` (non-test), captures plots/files as artifacts |
| `make_chart` | **new** | Sandboxed matplotlib → PNG artifact, reused in DOCX/PPTX |
| `request_human_approval` | exists | |

### 3.4 Multimodal pipeline (R7, R14)

**Triage first.** Each page is classified cheaply (text-layer check, image statistics, a quick VLM label if needed) and routed:

| Page type | Path |
|---|---|
| Born-digital | Text layer, no OCR |
| Typed scan | Tesseract, VLM only on low-confidence regions |
| Handwritten | Crop → VLM transcription → confidence → flagged for review if low |
| Engineering drawing / P&ID | Tile the drawing → VLM per tile → tag regex (`[A-Z]{1,3}-\d{2,4}`) cross-check → merge into an equipment/instrument table |
| Photograph | VLM defect review with location |
| Table | OCR with layout → structured table |

**Speed (hero run is ~5 min today, target < 90 s):**
- Downscale pages to ~1024 px long edge for the VLM, and send crops rather than whole pages
- Run the VLM only where OCR can't do the job (photo, handwriting, drawing)
- Cap `num_predict` and ask for JSON
- Batch all VLM steps in one resident window, so it's one model swap per run instead of several

**Visual grounding (signature feature).** The VLM is asked for boxes (Qwen2.5-VL supports grounding output). Every finding carries `{page, bbox, quote}`. The UI draws boxes on the page image. Click a finding and the page scrolls and highlights the region, and the reverse works too.

### 3.5 Knowledge base connector (R9)

- **Sources:** watched folders (drop a manual in, it gets indexed), `.eml`/`.msg` mail with attachments, PDF, DOCX, XLSX, scanned PDFs through the OCR path.
- **Collections with metadata:** department, document type, revision, date, classification. Retrieval can filter: "only current-revision SOPs".
- **Retrieval:** dense + BM25 (exists) → **cross-encoder reranker** (fastembed ONNX, CPU, no torch) → top 5.
- **Supersession:** a newer revision of an SOP marks the older one's chunks as superseded. They stay searchable but never get cited as current.
- **Citations that open:** click a citation and the source PDF page renders in the viewer with the passage highlighted (PyMuPDF search-for-text → rectangles).
- **Answer grounding check:** every sentence in the deliverable that cites a clause gets string-overlap checked against that chunk. An uncited or mismatched claim is flagged by the verifier.

### 3.6 Deliverables engine + Artifact Studio (R8)

| Type | Generator | Preview in the UI |
|---|---|---|
| DOCX | python-docx with templates (approval note, inspection summary, memo) | Page render (exists) |
| XLSX | openpyxl, **real formulas**, named ranges, a "Steps" sheet | Grid with formulas visible on hover, recalculated |
| PPTX | python-pptx with a corporate template, charts, speaker notes | Slide thumbnails plus a large slide view, rendered from our own structure so we avoid LibreOffice's RAM cost |
| Code | Workspace files | Syntax-highlighted, with the test run output beside it |
| Chart | Sandbox matplotlib | Inline image |

**Artifact Studio** opens as a right-side panel whenever a deliverable exists:
- Tabs per artifact, preview, download, SHA-256
- **Revise by instruction:** "shorten slide 3", "add a column for remaining life". The agent edits in place, and the Studio shows a **diff** between versions (text diff for DOCX/code, cell diff for XLSX, per-slide for PPTX)
- Version history per artifact, with the approval stamp tied to a specific version hash

### 3.7 Calculation engine (R8, "calculations with steps shown")

This is where "calculations with steps shown" gets done properly rather than the model writing arithmetic in prose.

- **Model's job:** identify the calculation and its inputs from the documents, e.g. remaining wall thickness, corrosion rate, remaining life, pump power, pressure drop.
- **Engine's job:** `sympy` + `pint` (units) executes a **calculation graph**: named inputs with sources → formula → result, every step with units.
- **Library of vetted formulas** for the demo domain (corrosion rate, remaining life, MAWP-style thickness check, energy/cost savings). The model can only compose these or simple arithmetic. It cannot invent physics.
- **Shown as:** rendered step-by-step math in the UI, plus an XLSX with live formulas (change an input and Excel recomputes), plus a section in the DOCX.
- **What-if sliders (creative):** because the graph is explicit, the UI can re-evaluate it client-side. Drag "corrosion rate" and watch the remaining-life chart move. This is the "simulation" you were after, and it's honest because the maths is real.

### 3.8 Sandbox v2 (R6, R13)

- Keeps: `network_mode: none`, read-only rootfs, dropped caps, CPU/mem/PID limits, 60 s timeout
- Adds: `run_script` (not just tests), captured **plots and output files** as artifacts, a pre-baked offline wheelhouse (numpy, pandas, matplotlib, scipy), stdin data files from the workspace
- **Live console:** stdout streams to the run panel as it runs
- **Test evidence:** the first failing run, the repair diff and the passing run shown side by side

### 3.9 Sovereignty proof v2 (R1, R15), the part the PS calls "the actual proof"

Today we *probe* for egress. The PS asks for a **visible network monitor**. V2 gives four independent layers of proof:

1. **Netwatch service (live monitor).**
   - Static IPs per service in compose, so an IP maps to a service name with no Docker socket.
   - A sidecar with `NET_ADMIN`/`NET_RAW` on the Docker bridges streams `conntrack -E` (or tcpdump) events: src, dst, port, bytes.
   - Every flow is classified `internal` / `blocked-external` / `allowed-external` (the last should always be zero).
2. **DNS sinkhole.** A dnsmasq container is the only resolver on the internal network. It answers internal names only and **logs every query**. Any attempt to resolve `api.openai.com` or `huggingface.co` shows up by name, not just by IP.
3. **Egress firewall + counters.** An iptables DROP+LOG rule on the internal bridge. Blocked-packet counters are shown in the UI.
4. **Browser side.** An nginx CSP of `default-src 'self'` means the UI itself can't load or call anything external. It's verifiable in DevTools.

**Live Sovereignty Map (signature feature).** A topology view of all containers. Each live connection is drawn as an animated edge while it happens: worker → ollama pulses during inference, worker → qdrant during retrieval. External nodes (Internet, DNS root) sit greyed out at the edge. If anything tries, the edge flashes red and the count increments.

**"Canary" button.** Deliberately runs a sandboxed `curl https://example.com` and a DNS lookup, so judges *see* the block happen, get logged, and change nothing. That's proof by attempted violation, not by assertion.

**Pull-the-plug mode.** Disconnect Wi-Fi/Ethernet live, then run the hero flow. The map shows no change because nothing ever went out.

**Tamper-evident audit.** Each audit row stores `hash = sha256(prev_hash + row)`. An offline **verify chain** button recomputes it. Editing any row breaks the chain, which is visible in the UI.

**Per-run Sovereignty Report.** A one-click PDF/DOCX with the run's flows, DNS queries, models used, tool calls, artifact hashes, the approval record and the chain verification result. That's the thing an auditor at a PSU would actually file.

### 3.10 Security and governance

- Local user accounts (admin, engineer, approver) with the approver role required for the approval gate
- KB collections can be restricted by role
- **Classification banner:** artifacts carry a marking (INTERNAL / RESTRICTED) chosen per workspace and stamped on DOCX/PPTX headers
- **Sensitive-data detector:** flags PAN/Aadhaar/phone/email/bank patterns in outputs before approval. Useful for board decks that leave the department
- Retention settings for uploads, runs and history

### 3.11 UI/UX

Keep the current layout (sidebar · conversation · run panel) and add:

| View | Purpose |
|---|---|
| **Workbench** (exists) | Conversation threads, plan review, run panel, results as data |
| **Artifact Studio** (new panel) | Previews, revise-by-instruction, diffs, versions |
| **Evidence viewer** (new) | Scanned page with finding boxes, citation source with highlight |
| **Sovereignty Map** (new page) | Live topology, DNS log, canary, chain verify, report export |
| **Model Garden** (new page) | Registered models, health, VRAM, benchmark leaderboard, add model |
| **Knowledge** (new page) | Collections, connectors, supersession, ingestion status |
| **Evals** (new page) | Router accuracy, extraction accuracy, latency per task class |

Small things that make it feel like a product: a `⌘K` command palette, drag-drop anywhere, a keyboard-first approval (A / R), a history search box, and a toast when a watched folder gets a new document.

### 3.12 Evaluation and observability

- **Eval pack:** ~40 labelled cases across task classes: routing labels, golden findings for the inspection report, golden rows for spreadsheet questions, coding tasks with hidden tests, calc cases with known answers, citation-must-exist checks.
- **Metrics:** router accuracy, finding recall/precision, citation validity, test pass@1 / pass@repair, calc exactness, p50/p95 latency per class.
- Runs in CI (the existing pytest suite plus an `evals/` runner) and from the Evals page. Model Garden reuses it for scoring new models.
- **Traces:** per-step timing, tokens, model swap time. The run panel already shows most of this.

---

## 4. Creative features, ranked

Ordered by jury impact per unit of effort.

| # | Feature | Why it lands | Effort |
|---|---|---|---|
| 1 | **Live Sovereignty Map + Canary** | Turns the PS's hardest requirement into the most visual moment of the demo | M |
| 2 | **Visual grounding on scans** | "It found corrosion *here*" with a box on the page, the way Claude feels with images | M |
| 3 | **What-if calculation sliders** | A real simulation, backed by a real calculation graph, exported with live Excel formulas | M |
| 4 | **Artifact Studio with revise + diff** | "Make slide 3 shorter" and watch it change. Feels like Codex/Claude artifacts | M–L |
| 5 | **Plan review before execution** | The human steers the agent *before* it acts. Rare in hackathon agents | S |
| 6 | **P&ID digitizer → equipment list XLSX** | Covers "engineering drawings" concretely, and it's clearly useful to a refinery | M |
| 7 | **Tamper-evident audit + Sovereignty Report** | What a PSU auditor would ask for | S |
| 8 | **Model Garden auto-benchmark** | Proves "addable later without redesigning" live | M |
| 9 | **Citation → open source page highlighted** | Instant trust | S |
| 10 | **Pull-the-plug run** | Zero code, maximum drama | — |
| 11 | Offline speech-to-text for field notes (whisper.cpp) | Nice extension of "handwritten notes" to spoken ones | M, stretch |

---

## 5. Hardware profiles and performance budget

| Profile | GPU | Text / code | Vision | Router tie-break |
|---|---|---|---|---|
| **laptop** (yours) | 8 GB | Qwen3-8B Q4 · Qwen2.5-Coder-7B Q4 | Qwen2.5-VL-7B Q4 | Qwen3-1.7B on CPU |
| workstation | 24 GB | Qwen3-14B · Qwen2.5-Coder-14B | Qwen2.5-VL-7B fp16 | same |
| server | 80 GB+ | gpt-oss-120b / Qwen3-32B via vLLM | Qwen2.5-VL-72B | same |

**Latency targets on the laptop:**

| Flow | Today | Target |
|---|---|---|
| Spreadsheet question → note | ~17 s | < 20 s |
| Code fix + sandbox test | ~12 s | < 30 s including a repair |
| Scanned report → approval note | ~5 min | **< 90 s** |
| Drawing → equipment list | — | < 2 min |
| Model swap | ~20–30 s | Once per run at most |

**RAM budget.** WSL capped at 10 GB (done). Avoid LibreOffice. PPTX previews come from our own structure. The tiny router model is ~1 GB RAM. The reranker is ONNX on CPU, ~300 MB.

---

## 6. Build plan

You have a couple of days, so the plan is split by what the submission *needs* vs what makes it great. **P0 closes every visible PS gap. P1 and P2 are the maxed-out version.**

### P0: submission (≈ 2–3 days)

| # | Item | Closes | Est. |
|---|---|---|---|
| 1 | Add Qwen2.5-Coder-7B and route `coding` to it, with the routing card showing the reason | R3, R11, "handled differently" | 2 h |
| 2 | `read_file` / `write_file` / `list_files` tools | R6 explicitly | 2 h |
| 3 | Real `create_xlsx` (formulas + Steps sheet) and `create_pptx` (template, chart), plus previews | R8 | 6 h |
| 4 | Calculation engine v1 (pint + sympy, 5 vetted formulas), steps rendered in UI and in XLSX | R8 "calculations with steps shown" | 5 h |
| 5 | **Netwatch v1:** DNS sinkhole with query log, iptables DROP+LOG counters, conntrack flow feed, and a Sovereignty Map page with a canary button | R15, the explicit ask | 7 h |
| 6 | VLM speed pass: downscale, crop, cap tokens, batch VLM steps. Hero under 90 s | R12 at a demoable speed | 3 h |
| 7 | Visual grounding v1: boxes from the VLM drawn on the page in the evidence viewer | R7, signature feature | 4 h |
| 8 | Nginx CSP `default-src 'self'` | R1, R15 | 15 min |
| 9 | Demo script v2 covering all four expected items plus the proof | Submission | 1 h |

**About 30 hours.** Tight but realistic. If you have to cut, cut in this order: 7, then the PPTX half of 3, then 6. **Never cut 5**, since it's the one requirement the PS calls "the actual proof".

### P1: strong product (≈ 1 week)

- LLM planner with playbooks + schema validation + **plan review UI**
- Observer/replanner that inserts and retries steps
- Conversation threads and follow-ups, with local history
- KB connector: watched folder, `.eml` ingestion, metadata filters, supersession
- Cross-encoder reranker and citation → open source page highlighted
- Artifact Studio: revise-by-instruction + diffs + versions
- Tamper-evident audit chain + per-run Sovereignty Report export
- P&ID digitizer (tiling + tag cross-check → XLSX)
- Handwriting path with confidence flags
- Sandbox `run_script` + plots as artifacts + live console
- Eval pack v1 + Evals page

### P2: maxed out (≈ 2+ weeks)

- Model Garden with auto-benchmark and a router that learns from scores
- Runtime adapters for llama.cpp and OpenAI-compatible (vLLM) endpoints, plus the server profile
- Tiny router model tie-breaker on CPU
- What-if sliders over calculation graphs
- Roles and approver permissions, classification banners, sensitive-data detector
- Photo defect review path, table extraction path
- Offline speech-to-text for field notes
- Run replay (time-travel through a finished trace)

---

## 7. Submission demo storyline (~5 minutes)

Each beat maps to an "Expected Solution" line.

| Time | Beat | PS expectation |
|---|---|---|
| 0:00 | Open the **Sovereignty Map**. Pull the network cable. Hit **Canary**: the attempt is blocked, logged by name, and shows as a red edge | "no external calls … visible network monitor" |
| 0:40 | Drop the **scanned inspection report**. The router picks the VL model. OCR plus vision run, boxes appear on the page, SOP clauses are cited, the approval note DOCX previews, the run pauses and you approve | "read a scanned inspection report … approval note as a Word file" + multimodal |
| 2:00 | Ask for the **remaining-life calculation**. Steps are shown with units, the XLSX has live formulas, drag the what-if slider (if P2) | "calculations with steps shown" |
| 2:40 | Ask to **fix the code**. The router picks the *coder* model. Tests fail, the agent repairs, tests pass in the sandbox | "coding task run and verified in a sandbox" + auto-selection across task types |
| 3:30 | "Make a 4-slide deck for the board from this." PPTX slides preview | "PPT/Word/Excel files" |
| 4:10 | Back to the map: every flow internal, zero external. Export the **Sovereignty Report**. Verify the audit chain | The proof, as an artifact |

Keep the machine-temperature demo from the internal round as the 60-second opener for non-technical jurors.

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Conntrack/tcpdump behave differently under Docker Desktop's WSL VM | Static IPs + DNS log + iptables counters give proof even without flow capture. Test on day 1 |
| VLM grounding boxes are imprecise on a 7B model | Show boxes as "approximate region". Fall back to OCR word boxes when the finding quote matches OCR text, which is exact |
| Three models don't fit on 8 GB together | They never need to. One is resident, the scheduler batches same-model steps, and the coder and VL models are never needed in the same run |
| LLM planner produces an invalid plan mid-demo | Schema validation → playbook fallback. The demo path always has a playbook |
| RAM pressure returns | WSL cap (done), per-container limits (done), no LibreOffice, CPU models kept small |
| The model invents calculation physics | The engine only executes vetted formulas. The model supplies inputs, not equations |
| Time | P0 is ordered by what the PS literally asks for. Cut order is written down in §6 |

---

## 9. Decisions needed from you

1. **Demo domain for V2:** stay with refinery corrosion (matches MRPL and the PS exactly), or lead with the plain factory story and keep corrosion as the technical deep-dive? I'd do the second, as in §7.
2. **Coder model:** Qwen2.5-Coder-7B (~4.7 GB pull) is the clean way to show "coding handled differently". It needs one download before the venue.
3. **Netwatch privilege:** the sidecar needs `NET_ADMIN`/`NET_RAW`. It's the *monitor*, not the agent, and it has no Docker socket. Acceptable?
4. **History:** you said earlier you didn't want saved chats. The PS doesn't require them, but follow-ups do need a thread. Keep threads in memory for the session only, or persist them locally?
