import { Check, Cpu, Eye, FileText, Image, Lock, Search, Shield, Sparkle, Table, Terminal } from "../icons";

// What is real today is marked Working; everything else is honestly Roadmap.
const FEATURES = [
  {
    icon: Cpu, status: "working", title: "Automatic model routing",
    line: "The right local model for each request, chosen by rules, not another model.",
    steps: ["Reads the request and any files", "Matches file type and keywords", "Loads the best local model"],
    tryGoal: "Which machines are running above 85 degrees C?", sample: "machine_health_log.xlsx",
  },
  {
    icon: Eye, status: "working", title: "An agent you can watch",
    line: "It plans, calls tools and checks its own work, and every step is visible.",
    steps: ["Plans the steps", "Runs each tool, shows the result", "Verifies before it hands over"],
  },
  {
    icon: Image, status: "working", title: "Scanned pages & drawings",
    line: "On-device OCR plus a vision model. Slow on an 8 GB card, about 5 minutes.",
    steps: ["Renders each page", "Reads text with local OCR", "Vision model inspects the images"],
    tryGoal: "Draft an approval note from the attached scanned inspection report, using the corrosion SOP.",
    sample: "inspection_report.pdf",
  },
  {
    icon: Search, status: "working", title: "Answers from your documents",
    line: "Grounded in your own manuals and SOPs, with the page it came from.",
    steps: ["Searches your library", "Ranks the best passages", "Cites file and page"],
    tryGoal: "When must a machine be stopped immediately, and who has to approve a maintenance shutdown?",
  },
  {
    icon: Table, status: "working", title: "Spreadsheet analysis",
    line: "The filtering is real code over your file, so the matching rows are exact.",
    steps: ["Opens the workbook", "Applies your threshold", "Shows the matching rows"],
    tryGoal: "Which machines had downtime over 60 minutes? Summarise the impact on output.",
    sample: "machine_health_log.xlsx",
  },
  {
    icon: Terminal, status: "working", title: "Code, run and verified",
    line: "Generated code runs in an isolated sandbox with no network.",
    steps: ["Writes the fix", "Runs the tests in the sandbox", "Repairs once if they fail"],
    tryGoal: "Fix the off-by-one bug in this code so a reading exactly at the limit is not reported as a breach, and make the pytest tests pass.",
    sample: "coding_fixture.py",
  },
  {
    icon: FileText, status: "working", title: "Word documents you can read",
    line: "A real .docx with sources, previewed in the app before you sign.",
    steps: ["Drafts the note", "Checks headings and citations", "Preview or download"],
  },
  {
    icon: Check, status: "working", title: "Human approval gate",
    line: "It stops and waits. The agent has no way to approve its own work.",
    steps: ["Pauses at the gate", "You read the draft", "Your decision is stamped in"],
  },
  {
    icon: Lock, status: "working", title: "Proof it stays on site",
    line: "The agent and sandbox test their own connection and report it live.",
    steps: ["Probes the internet from inside", "Reports the result", "Shown under Proof of isolation"],
  },
  { icon: FileText, status: "roadmap", title: "PowerPoint & Excel output", line: "Decks and workbooks with live formulas." },
  { icon: Shield, status: "roadmap", title: "Live network monitor", line: "Every connection drawn in real time." },
  { icon: Sparkle, status: "roadmap", title: "Model garden", line: "Register a new open-weight model and benchmark it." },
  { icon: Search, status: "roadmap", title: "Mail & folder connectors", line: "Index a shared drive or an .eml archive." },
];

function Card({ feature, onTry }) {
  const Icon = feature.icon;
  const working = feature.status === "working";
  return (
    <div className={`gcard${working ? "" : " is-roadmap"}`} tabIndex={0}>
      <div className="gcard-top">
        <span className="hc-icon"><Icon /></span>
        <span className={`gchip ${working ? "ok" : "road"}`}>{working ? "Working" : "Roadmap"}</span>
      </div>
      <div className="gcard-title">{feature.title}</div>
      <div className="gcard-line">{feature.line}</div>

      {feature.steps && (
        <div className="gpop" role="tooltip">
          <div className="gpop-title">{feature.title}</div>
          <ol className="gpop-steps">
            {feature.steps.map((step, index) => (
              <li key={step} style={{ animationDelay: `${index * 0.55}s` }}>
                <span className="gpop-tick"><Check /></span>
                {step}
              </li>
            ))}
          </ol>
          {feature.tryGoal && (
            <button type="button" className="gpop-try" onClick={() => onTry(feature)}>
              Try this
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function Guide({ onTry }) {
  return (
    <div className="guide">
      <div className="guide-inner">
        <h1>How the workbench works</h1>
        <p className="guide-sub">
          Hover any card for a ten-second preview. <strong>Try this</strong> puts the
          example straight into the prompt box.
        </p>

        <div className="guide-legend">
          <span className="gchip ok">Working</span> runs today on this laptop
          <span className="gchip road">Roadmap</span> designed, not built yet
        </div>

        <div className="ggrid">
          {FEATURES.map((feature) => (
            <Card key={feature.title} feature={feature} onTry={onTry} />
          ))}
        </div>
      </div>
    </div>
  );
}
