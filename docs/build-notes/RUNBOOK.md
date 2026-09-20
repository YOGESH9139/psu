# Sovereign AI Workbench — Runbook

How to start it, what to feed it, and how to tell whether it worked.
SIH26117 / MRPL. Everything runs locally; nothing calls out.

> **Doing the jury demo?** Follow **[DEMO.md](DEMO.md)** — one story, four
> minutes, no domain knowledge needed. This file is the full reference.

---

## 0. Prerequisites (one time)

- Docker Desktop running (`docker info` must succeed)
- NVIDIA GPU with WSL2 passthrough — tested on 8 GB
- ~15 GB free disk for the two model weights

### Stop WSL eating your RAM — do this once

WSL2 defaults to claiming up to half your RAM (16 GB on a 32 GB machine) and
never handing it back. That is why Docker felt like it was consuming the whole
laptop. A `.wslconfig` in your user folder caps it; the file is already written.
Apply it:

```bash
wsl --shutdown
```

Start Docker Desktop again afterwards. The stack then lives inside a 10 GB
ceiling — measured usage is ~7 GB, almost all of it the model server — leaving
Windows the rest. Each container also has its own limit in `docker-compose.yml`,
so no single service can starve the others.

---

## 1. Start it

```bash
docker compose up -d
```

Wait ~40 s, then confirm every service is up:

```bash
docker compose ps
```

You want all eight: `api`, `worker`, `frontend`, `postgres`, `redis`, `qdrant`,
`ollama`, `sandbox`. Most should say `(healthy)`.

### First run only — pull the models

Weights live in a Docker volume and persist. If `ollama list` is empty:

```bash
docker compose exec ollama ollama pull qwen3:8b
```

```bash
docker compose exec ollama ollama pull qwen2.5vl:7b
```

~11 GB, takes a while. Verify with `docker compose exec ollama ollama list`.

### First run only — build the fixtures

```bash
docker compose run --rm --no-deps -v "D:/Code/psu/fixtures:/app/fixtures" worker python fixtures/generate_demo_fixtures.py
```

```bash
docker compose run --rm --no-deps -v "D:/Code/psu/fixtures:/app/fixtures" worker python fixtures/generate_fixtures.py
```

The first writes the plain-language demo pack (`machine_health_log.xlsx`,
`maintenance_policy.pdf`). The second writes the domain pack (scanned inspection
report, corrosion SOP, coding fixture).

---

## 2. Open it

**http://localhost:3000**

A React single-page app. Reference library and live system status on the left,
the conversation in the middle, proof-of-isolation panel behind the top-right
button. Ask a question, watch the steps stream in, answer the approval dialog
when it appears.

---

## 3. Load the reference library

Left panel → **Add a policy document** → `fixtures/maintenance_policy.pdf`.

Wait ~20 s. The list should show:

```
maintenance_policy.pdf          3
```

That's the policy the agent cites. Without it, the note has nothing to cite and
verification correctly fails.

> Index only what the demo needs. If both `maintenance_policy.pdf` and
> `corrosion_sop.pdf` are loaded, answers cite both and the story muddies.

---

## 4. What it can do

### A. Plant floor analysis — ~20 seconds *(this is the demo)*

- **File:** `fixtures/machine_health_log.xlsx`
- **Prompt:** `Which machines are running above 85 degrees C? Check them against our maintenance policy and draft a maintenance approval note.`

**Correct result:** routes to `spreadsheet-analysis` → `qwen3-8b`. Finds exactly
**3 machines — M-04, M-07, M-10** — and flags M-04 as HIGH PRIORITY for breaching
both the temperature and the vibration limit. Writes `analysis_note.docx` with
policy citations, pauses for approval, completes on Approve.

### B. Code + sandbox — ~12 seconds

- **File:** `fixtures/coding_fixture.py`
- **Prompt:** `Fix the off-by-one bug in this code so a reading exactly at the limit is not reported as a breach, and make the pytest tests pass.`

Routes to `coding`. Writes a file, runs pytest **inside the network-isolated
sandbox container**, `passed: true, exit_code: 0`. No approval gate — nothing
safety-relevant is being recommended. The generated `.py` is downloadable.

### C. Scanned document → approval note — ~5 minutes

- **Library:** index `fixtures/corrosion_sop.pdf` first
- **File:** `fixtures/inspection_report.pdf`
- **Prompt:** `Draft an approval note from the attached scanned inspection report, using the corrosion SOP.`

Routes to `multimodal-document` → `qwen25vl-7b`. Renders 3 pages, OCRs them
(~155 and ~110 words at 88–94% confidence), runs the vision model over the
photograph and the handwritten margin note, retrieves SOP clauses, writes and
verifies the note, pauses for approval.

> Slow — the vision model has to swap into VRAM. Don't demo this live.

---

## 5. How to check it actually worked

### In the UI

| What | Where | Working looks like |
|---|---|---|
| Routing | Right of the conversation, first card | Task type + model + confidence, shown before any step |
| Live trace | Under it | Steps appearing one at a time with durations |
| Findings | "What the agent found" | Plain-English findings with the filter expression as evidence |
| Citations | "Sources it relied on" | Real passages with file name and page number |
| Deliverable | "Generated document" | `.docx` with a SHA-256 and a Download button |
| Human gate | Modal dialog | Run stops until you Approve or Send back |
| Isolation | Top-right "Proof of isolation" | Green dots for agent and sandbox egress |

### From the command line

```bash
curl -s http://127.0.0.1:8000/api/sovereignty/status | python -m json.tool
```

Look for `egress.worker.egress_blocked: true`, `egress.sandbox.egress_blocked:
true`, `offline_capable: true`, and both models `healthy: true`.

What went wrong, if something did:

```bash
docker compose logs worker --tail=50
```

Full audit trail for a run:

```bash
curl -s http://127.0.0.1:8000/api/runs/<RUN_ID>/audit | python -m json.tool
```

### Run the test suite

103 tests — router, tool allowlist, path policy, DOCX generation and
verification, chunking, plain-language spreadsheet questions, and the agent's
approval gate, guards and repair loop.

```bash
docker exec psu-worker-1 rm -rf //app/tests //app/fixtures
```

```bash
docker cp D:/Code/psu/tests psu-worker-1:/app/tests && docker cp D:/Code/psu/pytest.ini psu-worker-1:/app/pytest.ini && docker cp D:/Code/psu/fixtures psu-worker-1:/app/fixtures
```

```bash
docker exec -w //app psu-worker-1 python -m pytest tests -q
```

Expected: `103 passed`.

---

## 6. Sovereignty claims you can prove live

All measured, none asserted.

**The agent container cannot reach the internet.** It probes 8.8.8.8 and 1.1.1.1
from inside itself every 10 s and reports the result:

```bash
docker compose exec worker python -c "import socket; socket.create_connection(('8.8.8.8',443),timeout=3)"
```

Expect `OSError: [Errno 101] Network is unreachable`.

**The sandbox is harder-isolated still** — `network_mode: none`, read-only root
filesystem, all Linux capabilities dropped, 512 MB, 1 CPU, 64 PIDs, 60 s
timeout. Agent-written code executes there and nowhere else.

**The agent cannot approve its own work.** No tool in the allowlist writes to the
`approval_decisions` table — a test asserts that against the source. The run
blocks until a row appears, and reads the decision from Postgres, never from the
queue message that woke it.

**Nothing is downloaded at runtime.** The embedding model is baked into the
worker image at build time; `HF_HUB_OFFLINE=1` at runtime. That is why
`pip install` inside the worker fails — correctly.

### Air-gapped run

```bash
docker compose -f docker-compose.yml -f docker-compose.airgap.yml up -d
```

Removes the model server's only outbound network. Pull the weights first.

---

## 7. If something breaks

| Symptom | Cause | Fix |
|---|---|---|
| `Could not load model ... into the local model server` | GPU out of VRAM | Close Chrome. `docker compose restart ollama`. Check `nvidia-smi` |
| Run fails at PREFLIGHT | Ollama has no models | `docker compose exec ollama ollama list`, pull if empty |
| Note has 0 citations | Policy not indexed | Do step 3 |
| Status dots stay grey | Worker not reporting yet | Wait 10 s for the next poll, then `docker compose restart worker` |
| `docker compose ps` empty | Docker Desktop stopped | Restart it, then `docker compose up -d` |
| Frontend loads but no data | api down | `docker compose logs api --tail=30` |

Full reset (destroys uploads, runs and the index — **not** the model weights):

```bash
docker compose down && docker volume rm psu_postgres_data psu_qdrant_data psu_run_workspaces psu_uploads && docker compose up -d
```

---

## 8. Known gaps

Honest list, so nothing surprises you in the room.

- **The scanned-document flow takes ~5 minutes**, against the <4 min target in
  plan.md. Vision inference on an 8 GB card is the bottleneck. Fine to mention,
  don't demo live.
- **Plan skeletons are deterministic per task class.** The tool *sequence* is
  fixed; what goes *into* the deliverable — the retrieval query, the findings,
  the recommended action, the generated code — comes from the local model
  reading real tool output. Nothing in the document is hardcoded.
- **Retrieval fusion is RRF, not a cross-encoder reranker.**
  `bge-reranker-v2-m3` would need torch in the worker image.
  `infra/models.yaml` says so rather than claiming otherwise.
- **PPTX/XLSX generation are declared stubs** returning `{"status": "roadmap"}`,
  as plan.md intended.
- **The repair loop is wired and unit-tested but has not fired in a live demo** —
  the model fixed the fixture bug on its first attempt.
- **Ambiguous questions are refused, not guessed.** "Which machines are over 85?"
  with no unit returns statistics and says the column was ambiguous, because
  temperature, units produced and downtime all span that value.
