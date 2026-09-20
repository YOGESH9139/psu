import { api, fetchSample } from "./api";

// A workspace is a general engine plus its own reference library and starter
// tasks. Templates only decide the starting point; anything can be asked anywhere.
export const TEMPLATES = [
  {
    key: "plant-maintenance",
    name: "Plant Maintenance",
    blurb: "Shift logs, machine readings and the maintenance policy.",
    banner: "INTERNAL",
    library: ["maintenance_policy.pdf"],
    tasks: [
      {
        icon: "table",
        label: "Machines running too hot",
        hint: "shift log + policy",
        goal:
          "Which machines are running above 85 degrees C? Check them against our " +
          "maintenance policy and draft a maintenance approval note.",
        sample: "machine_health_log.xlsx",
      },
      {
        icon: "table",
        label: "Where the shift lost time",
        hint: "downtime breakdown",
        goal: "Which machines had downtime over 60 minutes? Summarise the impact on output.",
        sample: "machine_health_log.xlsx",
      },
      {
        icon: "ask",
        label: "What does the policy say?",
        hint: "answered from your library",
        goal:
          "When must a machine be stopped immediately, and who has to approve a " +
          "maintenance shutdown?",
      },
    ],
  },
  {
    key: "engineering-code",
    name: "Engineering & Code",
    blurb: "Internal tools, scripts and the testing standard.",
    banner: "INTERNAL",
    library: ["engineering_standards.pdf"],
    tasks: [
      {
        icon: "code",
        label: "Fix a bug and test it",
        hint: "runs in the sandbox",
        goal:
          "Fix the off-by-one bug in this code so a reading exactly at the limit is " +
          "not reported as a breach, and make the pytest tests pass.",
        sample: "coding_fixture.py",
      },
      {
        icon: "ask",
        label: "What does our standard require?",
        hint: "answered from your library",
        goal: "What does our standard require when a value is exactly equal to the limit?",
      },
    ],
  },
  {
    key: "finance-procurement",
    name: "Finance & Procurement",
    blurb: "Vendor quotes and the purchase approval policy.",
    banner: "RESTRICTED",
    library: ["procurement_policy.pdf"],
    tasks: [
      {
        icon: "table",
        label: "Quotes above the approval limit",
        hint: "quotes + procurement policy",
        goal:
          "Which vendor quotes have total cost above 500000 INR? Check them against " +
          "the procurement policy and draft an approval note.",
        sample: "vendor_quotes.xlsx",
      },
      {
        icon: "ask",
        label: "Who can approve what?",
        hint: "answered from your library",
        goal: "Who has to approve a purchase above 500000 INR, and how many quotes are needed?",
      },
    ],
  },
  {
    key: "blank",
    name: "Blank workspace",
    blurb: "Start empty. Add your own documents and ask anything.",
    banner: "INTERNAL",
    library: [],
    tasks: [],
  },
];

export const templateOf = (key) => TEMPLATES.find((t) => t.key === key) || TEMPLATES[TEMPLATES.length - 1];

/** Upload and index the template's reference documents into a workspace. */
export async function loadLibrary(template, workspaceId, onProgress) {
  for (const name of template.library) {
    onProgress?.(`Indexing ${name}…`);
    const file = await fetchSample(name);
    const uploaded = await api.uploadFile(file);
    await api.ingest(uploaded.file_id, workspaceId);
  }
}
