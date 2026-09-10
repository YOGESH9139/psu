# PHASE 3 — Post-Demo / Production Hardening

> **Do not touch these during the hackathon.** This file exists so nothing gets forgotten.  
> Everything in Phase 1 that was deliberately cut to scope is tracked here.

---

## Infrastructure

- [ ] Multi-GPU scheduling and model sharding (>8 GB VRAM profiles: 14B on 24 GB, 32B on 48 GB)
- [ ] Distributed Compose → Kubernetes / Helm chart
- [ ] Proper secrets management (Vault or K8s Secrets) instead of `.env` files
- [ ] Container image signing and SBOM generation
- [ ] Automated image digest locking and reproducible builds
- [ ] Full gVisor sandbox isolation (replaces the pre-warmed container approach)

## Agent & Memory

- [ ] Cross-run episodic memory (agent remembers outcomes of previous runs for the same user/project)
- [ ] Long-term knowledge graph from audit events (entity extraction → Neo4j or similar)
- [ ] Multi-turn conversational refinement within a session
- [ ] Parallel tool execution (LangGraph `Send` API for concurrent tool calls)
- [ ] Agent self-reflection / critique loop (more than one repair cycle for code)
- [ ] Configurable retry and backoff policy per tool

## RAG & Knowledge

- [ ] Incremental re-ingestion on document update (hash-diff, not full re-index)
- [ ] Multi-lingual support (BGE-M3 already multilingual; OCR needs tesseract-data for each language)
- [ ] Semantic chunking (replace page-boundary chunking with LlamaIndex sentence-window)
- [ ] Knowledge graph-augmented RAG
- [ ] User-level knowledge base namespacing (multi-user isolation)

## Tools & Artifacts

- [ ] `create_calculation_xlsx` — fully functional XLSX generation with formulas
- [ ] `create_presentation_pptx` — fully functional PPTX generation with charts
- [ ] Structured table extraction from PDFs (pdfplumber + LLM re-formatting)
- [ ] Drawing/P&ID object detection (fine-tuned YOLO or RT-DETR on industrial drawings)
- [ ] Live connector tools (internal database reader, REST API client for approved internal systems)

## Security & Compliance

- [ ] Enterprise SSO (OIDC/SAML)
- [ ] Role-based access control (approver vs. analyst vs. read-only)
- [ ] FIPS-compliant crypto for artifact hashing
- [ ] Audit log export in SIEM-compatible format (CEF / JSON-L)
- [ ] Annual penetration test and threat model review
- [ ] Formal data-at-rest encryption for uploaded documents

## Frontend & UX

- [ ] Multi-user collaboration (shared run view, comment threads)
- [ ] Notification system (email / Teams / Slack for approval requests)
- [ ] Run history and search
- [ ] Diff view for approved vs. rejected artifact versions
- [ ] Mobile-responsive layout

## Productionisation

- [ ] Automated golden-fixture regression suite in CI
- [ ] Latency SLO monitoring (< 4-min hero run threshold enforced in CI)
- [ ] Model performance benchmarks on real (redacted) documents
- [ ] Formal engineering certification disclaimer review with legal
- [ ] Vendor/OSS licence audit
