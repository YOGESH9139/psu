import { useEffect, useRef, useState } from "react";
import { Alert, Check, Eye, X } from "../icons";

/**
 * The human gate. The run is genuinely blocked in the worker until this posts a
 * decision — closing the dialog does not release it, so there is no dismiss
 * affordance beyond making a real choice.
 */
export default function ApprovalDialog({ approval, onDecide, onReadDraft }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(null);
  const approveRef = useRef(null);

  useEffect(() => {
    approveRef.current?.focus();
  }, []);

  if (!approval) return null;

  async function decide(decision) {
    if (decision === "reject" && !note.trim()) {
      setError("Say what needs to change, so the agent can revise it.");
      return;
    }
    setPending(decision);
    setError("");
    try {
      await onDecide(decision, note.trim());
    } catch (e) {
      setError(e.message);
      setPending(null);
    }
  }

  const findings = approval.findings || [];
  const citations = approval.citations || [];
  const high = findings.filter(
    (f) => String(f.severity || "").toLowerCase() === "high"
  ).length;

  return (
    <div className="backdrop">
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="approval-title">
        <div className="dialog-head">
          <div className="dialog-icon"><Alert /></div>
          <div>
            <h3 id="approval-title">Your approval is required</h3>
            <p>
              The agent has drafted a document but cannot finalise it. Nothing is
              recorded until you decide.
            </p>
          </div>
        </div>

        <div className="dialog-body">
          <div className="dialog-summary">{approval.summary}</div>

          {onReadDraft && (
            <button type="button" className="read-draft" onClick={onReadDraft}>
              <Eye />
              Read the draft before deciding
            </button>
          )}

          <div className="dialog-facts">
            <div className="fact">
              <div className="k">Findings</div>
              <div className="v">{findings.length}</div>
            </div>
            <div className="fact">
              <div className="k">High severity</div>
              <div className="v" style={high ? { color: "var(--bad)" } : undefined}>{high}</div>
            </div>
            <div className="fact">
              <div className="k">Sources cited</div>
              <div className="v">{citations.length}</div>
            </div>
          </div>

          <div className="dialog-note">
            <label htmlFor="approval-note">
              Note {pending === "reject" ? "" : "(required if you send it back)"}
            </label>
            <input
              id="approval-note"
              type="text"
              value={note}
              placeholder="e.g. wrong machine — check M-07 instead"
              onChange={(e) => {
                setNote(e.target.value);
                setError("");
              }}
              disabled={Boolean(pending)}
            />
            {error && <div className="err">{error}</div>}
          </div>
        </div>

        <div className="dialog-foot">
          <button
            type="button"
            className="btn btn-reject"
            onClick={() => decide("reject")}
            disabled={Boolean(pending)}
          >
            <X style={{ width: 14, height: 14, verticalAlign: "-2px", marginRight: 6 }} />
            {pending === "reject" ? "Sending back…" : "Send back"}
          </button>
          <button
            ref={approveRef}
            type="button"
            className="btn btn-approve"
            onClick={() => decide("approve")}
            disabled={Boolean(pending)}
          >
            <Check style={{ width: 14, height: 14, verticalAlign: "-2px", marginRight: 6 }} />
            {pending === "approve" ? "Recording…" : "Approve"}
          </button>
        </div>

        <div className="dialog-foot-note">
          Your decision is written to the audit log and stamped into the document.
          The agent has no way to record it for you.
        </div>
      </div>
    </div>
  );
}
