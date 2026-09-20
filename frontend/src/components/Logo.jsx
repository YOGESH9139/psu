// The mark: a node held inside a boundary — the workbench, and the line nothing crosses.
export default function Logo({ size = 30 }) {
  return (
    <svg
      className="logo"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-label="Sovereign Workbench"
    >
      <defs>
        <linearGradient id="logo-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#9A5CFF" />
          <stop offset="1" stopColor="#5417E0" />
        </linearGradient>
      </defs>
      <rect x="0.5" y="0.5" width="31" height="31" rx="9.5" fill="url(#logo-g)" />
      <path
        d="M16 4.6l10.2 5.9v11L16 27.4 5.8 21.5v-11z"
        fill="none"
        stroke="#fff"
        strokeWidth="1.7"
        strokeLinejoin="round"
        opacity="0.95"
      />
      <path
        d="M16 12.6V9M18.9 17.5l3.1 1.8M13.1 17.5L10 19.3"
        stroke="#fff"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.75"
      />
      <circle cx="16" cy="16" r="3.1" fill="#fff" />
    </svg>
  );
}
