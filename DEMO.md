# Demo script — 4 minutes

One story, told in plain language. No domain knowledge required from the jury.

**The story:** a factory logs machine readings at the end of every shift. The
supervisor has to spot which machines are in trouble, check them against the
plant's own maintenance policy, and write an approval note. That takes them
twenty minutes and a phone call. Here it takes twenty seconds — and a human
still signs it.

---

## Before you walk in

```bash
docker compose up -d
```

Then, in the app at **http://localhost:3000**, left panel → **Add a policy
document** → `fixtures/maintenance_policy.pdf`. Wait until it shows `3` chunks.

> Index **only** `maintenance_policy.pdf`. If `corrosion_sop.pdf` is also in the
> library the agent will cite both, which muddies the story. To clear the
> library: `docker compose down && docker volume rm psu_postgres_data psu_qdrant_data && docker compose up -d`

Have `fixtures/machine_health_log.xlsx` ready to drag in. Check the three dots
in the left panel are green. Close Chrome tabs you don't need.

---

## The demo

### 1. Set the scene — 20 seconds

> "This is a plant floor assistant. It runs entirely on this laptop — no cloud,
> no internet. Watch the left panel: it's telling me it *cannot* reach the
> internet, and it checked that itself a few seconds ago."

Point at the three green dots. Don't explain them yet.

### 2. Ask the question — 15 seconds

Drag `machine_health_log.xlsx` into the box and type:

```
Which machines are running above 85 degrees C? Check them against our
maintenance policy and draft a maintenance approval note.
```

> "This is the end-of-shift log — twelve machines, temperature, vibration,
> output, downtime. I'm asking in plain English."

Press Enter.

### 3. Narrate the live trace — 20 seconds

The steps appear one by one. Let them run; talk over them.

> "It picked the model by itself — nobody chose it. It opened the spreadsheet,
> found three machines over the limit, and now it's searching *our* policy
> document to find out what the rule actually says."

The key line to land: **"I never told it what 85 degrees means. It looked that
up in our own policy."**

### 4. The approval popup — 40 seconds

The dialog appears and the run stops.

> "Here's the important part. It has written the note — but it has stopped.
> It found three machines, all high severity, and it cited five passages from
> our policy. And it is asking me."

Read the summary aloud — it names the machine, the temperature, the vibration,
and why that's high priority.

> "This isn't a UI nicety. The agent is genuinely blocked in the background.
> There is no code path anywhere in this system that lets it approve its own
> work. A person has to answer."

Click **Approve**.

### 5. The result — 40 seconds

> "Three findings, in plain English. Every one traceable — this line came from
> page 1 of our policy, this from page 2. And a Word document I can send to
> maintenance right now."

Scroll to the citations, then the document card. Click **Download** and open it.

> "Notice the last section — my decision, with my name and a timestamp, written
> into the document itself. Before I clicked, it said PENDING."

### 6. The proof — 45 seconds

Click **Proof of isolation** (top right).

> "Everything I just claimed, measured rather than asserted. The agent container
> probed the internet a few seconds ago and could not get out. The sandbox where
> generated code runs has no network interface at all. Zero external
> integrations, zero cloud credentials — because none exist in this deployment.
>
> And the audit trail: every step, every tool, my approval. Append-only."

### 7. Close — 20 seconds

> "Twenty seconds, on one laptop, with the network unplugged. The data never
> left this machine, the reasoning is traceable to our own documents, and a human
> still signs. That's the whole idea."

---

## If a juror asks

**"Is this just ChatGPT with extra steps?"**
> No cloud model is involved. Two models run on this GPU — one for text, one for
> images — and the system picks between them automatically. Unplug the network
> and the demo runs identically.

**"How do I know it isn't making the numbers up?"**
> The numbers come from a real filter over the spreadsheet, not from the model —
> you can see the expression under each finding: `temperature_c > 85.0`. The
> model writes the explanation; the arithmetic is deterministic. And every policy
> claim carries the file and page it came from.

**"What if it's wrong?"**
> Then you click Send back with a note and it revises once. And it can't finalise
> anything without you either way.

**"Does it only do spreadsheets?"**
> No — show them: it also reads scanned documents with OCR and a vision model,
> and it writes and runs code in an isolated sandbox. *(Only offer the coding
> demo if you have time; skip the scanned-report one, it takes ~5 minutes.)*

**"Why does that matter for a public sector unit?"**
> Inspection reports, tender documents, safety records — none of that can be
> pasted into a cloud service. This gives the same assistance with the data
> staying inside the building.

---

## Backup: the coding demo — 15 seconds

If the first demo lands and you have time. New analysis → attach
`fixtures/coding_fixture.py`:

```
Fix the off-by-one bug in this code so a reading exactly at the limit is not
reported as a breach, and make the pytest tests pass.
```

> "Different question, so it picked the coding model instead. It wrote the fix
> and ran the tests — in a container with no network, a read-only filesystem and
> a 60-second kill timer. That's where you'd want AI-written code to run."

---

## Do not demo live

- **The scanned inspection report.** It works, but takes ~5 minutes because the
  vision model has to swap into VRAM. Mention it, show a screenshot if asked.
- **The air-gapped compose overlay.** Talk about it; don't restart the stack.

---

## If something breaks

| Problem | Do this |
|---|---|
| Dots aren't green | Wait 10 s for the next poll. If still red, `docker compose restart worker` |
| Run fails at the model step | GPU is full. Close Chrome, `docker compose restart ollama` |
| "0 citations" in the note | The policy wasn't indexed. Add it and re-run |
| Whole stack is down | `docker compose up -d`, wait 40 s |

If a run fails live: don't debug it. Say *"local GPU, shared laptop"*, click
**New analysis**, and run it again. It takes twenty seconds.
