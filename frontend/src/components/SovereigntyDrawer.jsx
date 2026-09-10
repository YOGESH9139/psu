import { Cpu } from "../icons";

function time(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString() : "";
}

export default function SovereigntyDrawer({ status }) {
  if (!status) {
    return (
      <aside className="drawer">
        <div className="drawer-sub">Contacting the local API…</div>
      </aside>
    );
  }

  const egress = status.egress || {};
  const level = (probe) =>
    !probe?.reporting ? "warn" : probe.egress_blocked ? "ok" : "bad";

  const checks = [
    {
      level: level(egress.worker),
      label: "The agent cannot reach the internet",
      detail: egress.worker?.reporting
        ? `probed from inside the agent container ${egress.worker.age_seconds}s ago`
        : "the agent has not reported yet",
    },
    {
      level: level(egress.sandbox),
      label: `Code sandbox network: ${status.sandbox_network_mode}`,
      detail: egress.sandbox?.reporting
        ? `probed from inside the sandbox ${egress.sandbox.age_seconds}s ago`
        : "the sandbox has not reported yet",
    },
    {
      level: status.offline_capable ? "ok" : "warn",
      label: "Works with the network unplugged",
      detail: "true only when the agent and the sandbox both measure zero egress",
    },
    {
      level: (status.external_integrations || []).length ? "bad" : "ok",
      label: "No external integrations configured",
      detail: `${(status.cloud_credentials || []).length} cloud credentials exist in this deployment`,
    },
  ];

  return (
    <aside className="drawer">
      <div>
        <h3>Measured isolation</h3>
        <div className="drawer-sub">
          Live probes, not configuration claims · {time(status.timestamp)}
        </div>
      </div>

      <div>
        {checks.map((check) => (
          <div className="check" key={check.label}>
            <span className={`dot ${check.level}`} />
            <div className="ctext">
              <div className="clabel">{check.label}</div>
              <div className="cdetail">{check.detail}</div>
            </div>
          </div>
        ))}
      </div>

      <div>
        <h3>Local models</h3>
        <div>
          {(status.model_endpoints || []).map((model) => (
            <div className="endpoint" key={model.id}>
              <span className={`dot ${model.healthy ? "ok" : "bad"}`} />
              <Cpu style={{ width: 12, height: 12, opacity: 0.5 }} />
              {model.ollama_model}
            </div>
          ))}
        </div>
      </div>

      <div>
        <h3>Audit trail</h3>
        <div className="drawer-sub">Append-only · most recent first</div>
        <div className="audit" style={{ marginTop: 9 }}>
          {(status.audit_tail || []).map((event) => (
            <div
              className={`audit-row${event.blocked_tool_attempt ? " blocked" : ""}${
                event.approval_decision ? " approval" : ""
              }`}
              key={event.id}
            >
              <span className="t">{time(event.created_at)}</span>
              <span>
                {[event.event_type, event.tool_name, event.approval_decision]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
