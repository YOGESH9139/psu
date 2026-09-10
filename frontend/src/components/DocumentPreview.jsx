import { useEffect, useState } from "react";
import { api, formatBytes } from "../api";
import { Download, X } from "../icons";

/** Renders the structured blocks the API extracts from a .docx as a page. */
function DocumentBody({ blocks }) {
  return (
    <div className="doc-page">
      {blocks.map((block, index) => {
        switch (block.type) {
          case "title":
            return <h1 className="doc-title" key={index}>{block.text}</h1>;
          case "heading":
            return (
              <h2 className={`doc-h doc-h${block.level}`} key={index}>
                {block.text}
              </h2>
            );
          case "bullet":
            return (
              <div className="doc-bullet" key={index}>
                <span className="doc-dot" />
                <span>{block.text}</span>
              </div>
            );
          case "fields":
            return (
              <dl className="doc-fields" key={index}>
                {block.rows.map(([key, value], i) => (
                  <div key={i}>
                    <dt>{key}</dt>
                    <dd>{value || "—"}</dd>
                  </div>
                ))}
              </dl>
            );
          case "table":
            return (
              <div className="doc-table-wrap" key={index}>
                <table className="doc-table">
                  <thead>
                    <tr>{block.header.map((cell, i) => <th key={i}>{cell}</th>)}</tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, r) => (
                      <tr key={r}>{row.map((cell, c) => <td key={c}>{cell || "—"}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          default:
            return <p className="doc-p" key={index}>{block.text}</p>;
        }
      })}
    </div>
  );
}

export default function DocumentPreview({ artifact, onClose }) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    setPreview(null);
    setError("");
    fetch(api.downloadUrl(artifact.preview_url))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((data) => !cancelled && setPreview(data))
      .catch((e) => !cancelled && setError(e.message));
    return () => { cancelled = true; };
  }, [artifact.preview_url]);

  return (
    // Sits above the approval dialog: the reader opens it FROM that dialog.
    <div className="backdrop is-viewer" onClick={onClose}>
      <div className="viewer" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="viewer-head">
          <div className="viewer-title">
            <div className="vt-name">{artifact.filename}</div>
            <div className="vt-sub">
              {formatBytes(artifact.size_bytes)} · sha256 {String(artifact.sha256).slice(0, 20)}…
            </div>
          </div>
          <a
            className="dl-btn"
            href={api.downloadUrl(artifact.download_url)}
            download={artifact.filename}
          >
            <Download />
            Download
          </a>
          <button type="button" className="icon-btn" onClick={onClose} title="Close">
            <X />
          </button>
        </header>

        <div className="viewer-body">
          {error && <div className="viewer-msg">Could not load a preview: {error}</div>}
          {!preview && !error && <div className="viewer-msg">Loading preview…</div>}

          {preview?.kind === "document" && <DocumentBody blocks={preview.blocks} />}

          {preview?.kind === "text" && (
            <pre className="doc-code">
              <code>{preview.content}</code>
            </pre>
          )}

          {preview && !["document", "text"].includes(preview.kind) && (
            <div className="viewer-msg">{preview.message}</div>
          )}

          {preview?.truncated && (
            <div className="viewer-msg">Preview truncated — download for the full file.</div>
          )}
        </div>
      </div>
    </div>
  );
}
