// Inline SVG only — no icon font, no sprite fetch, nothing to load offline.
const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

const make = (paths) => (props) => (
  <svg {...base} {...props}>
    {paths}
  </svg>
);

export const Shield = make(
  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
);
export const Sparkle = make(
  <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" />
);
export const Plus = make(<><path d="M12 5v14" /><path d="M5 12h14" /></>);
export const Paperclip = make(
  <path d="M21.4 11.05l-9.19 9.19a5 5 0 01-7.07-7.07l9.19-9.19a3.5 3.5 0 014.95 4.95l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
);
export const Send = make(<><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4 20-7z" /></>);
export const X = make(<><path d="M18 6L6 18" /><path d="M6 6l12 12" /></>);
export const Check = make(<path d="M20 6L9 17l-5-5" />);
export const Alert = make(
  <><path d="M12 9v4" /><path d="M12 17h.01" />
  <path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" /></>
);
export const FileText = make(
  <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
  <path d="M14 2v6h6" /><path d="M16 13H8" /><path d="M16 17H8" /></>
);
export const Download = make(
  <><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
  <path d="M7 10l5 5 5-5" /><path d="M12 15V3" /></>
);
export const ChevronRight = make(<path d="M9 18l6-6-6-6" />);
export const Lock = make(
  <><rect x="3" y="11" width="18" height="11" rx="2" />
  <path d="M7 11V7a5 5 0 0110 0v4" /></>
);
export const Book = make(
  <><path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
  <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" /></>
);
export const Cpu = make(
  <><rect x="4" y="4" width="16" height="16" rx="2" />
  <rect x="9" y="9" width="6" height="6" />
  <path d="M9 2v2" /><path d="M15 2v2" /><path d="M9 20v2" /><path d="M15 20v2" />
  <path d="M2 9h2" /><path d="M2 15h2" /><path d="M20 9h2" /><path d="M20 15h2" /></>
);
export const Search = make(
  <><circle cx="11" cy="11" r="8" /><path d="M21 21l-4.3-4.3" /></>
);
export const Table = make(
  <><rect x="3" y="3" width="18" height="18" rx="2" />
  <path d="M3 9h18" /><path d="M3 15h18" /><path d="M9 3v18" /></>
);
export const Terminal = make(<><path d="M4 17l6-6-6-6" /><path d="M12 19h8" /></>);
export const Image = make(
  <><rect x="3" y="3" width="18" height="18" rx="2" />
  <circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></>
);
export const Eye = make(
  <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
  <circle cx="12" cy="12" r="3" /></>
);
export const Refresh = make(
  <><path d="M3 12a9 9 0 019-9 9 9 0 016.7 3L21 8" /><path d="M21 3v5h-5" />
  <path d="M21 12a9 9 0 01-9 9 9 9 0 01-6.7-3L3 16" /><path d="M3 21v-5h5" /></>
);

// Which glyph represents each tool in the activity timeline.
export const toolIcon = (tool) =>
  ({
    extract_pdf_pages: FileText,
    run_ocr: FileText,
    inspect_image: Image,
    search_knowledge: Search,
    read_source_excerpt: Book,
    read_spreadsheet: Table,
    analyze_spreadsheet: Table,
    create_approval_docx: FileText,
    verify_docx: Check,
    write_code_file: Terminal,
    run_code_tests: Terminal,
    list_run_artifacts: FileText,
    request_human_approval: Lock,
  }[tool] || Sparkle);
