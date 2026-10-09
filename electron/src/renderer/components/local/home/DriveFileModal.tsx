import React, { useState, useEffect, useCallback } from "react";
import {
  X, Copy, Check, ExternalLink, FileText, File,
  FolderOpen, Image as ImageIcon, Loader2, AlertTriangle,
} from "lucide-react";
import { useAppSelector } from "@/store/hooks";
import type { DriveFile } from "./DriveFileCards";

interface DriveFileModalProps {
  file: DriveFile;
  onClose: () => void;
}

type ContentType = "text" | "csv" | "image" | "binary";

interface FileData {
  success: boolean;
  name: string;
  mime_type: string;
  size_bytes: number;
  content_type: ContentType;
  content: string | null;
  truncated?: boolean;
  link?: string;
  note?: string;
  error?: string;
}

function getApiBase(): string {
  return (import.meta as unknown as { env: { VITE_API_BASE_URL?: string } })
    .env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ─── CSV table renderer ────────────────────────────────────────────────────────

function CsvTable({ csv }: { csv: string }) {
  const lines = csv.split("\n").filter(l => l.trim());
  const rows = lines.slice(0, 200).map(l => {
    // simple CSV parse — handles basic quoted fields
    const cells: string[] = [];
    let cur = "";
    let inQ = false;
    for (let i = 0; i < l.length; i++) {
      const c = l[i];
      if (c === '"') { inQ = !inQ; continue; }
      if (c === "," && !inQ) { cells.push(cur); cur = ""; continue; }
      cur += c;
    }
    cells.push(cur);
    return cells;
  });

  if (!rows.length) return null;
  const [header, ...body] = rows;
  const cols = Math.max(...rows.map(r => r.length));

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{
        borderCollapse: "collapse",
        fontSize: 11, fontFamily: "'Geist Mono', monospace",
        minWidth: "100%",
      }}>
        <thead>
          <tr>
            {Array.from({ length: cols }, (_, i) => (
              <th key={i} style={{
                padding: "6px 10px",
                background: "rgba(217,119,87,0.08)",
                borderBottom: "1px solid var(--sp-line-2)",
                borderRight: "1px solid var(--sp-line)",
                color: "var(--sp-ink-2)",
                fontWeight: 600,
                textAlign: "left",
                whiteSpace: "nowrap",
              }}>
                {header[i] ?? ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri} style={{ background: ri % 2 === 0 ? "transparent" : "rgba(255,255,255,0.02)" }}>
              {Array.from({ length: cols }, (_, ci) => (
                <td key={ci} style={{
                  padding: "5px 10px",
                  borderBottom: "1px solid var(--sp-line)",
                  borderRight: "1px solid var(--sp-line)",
                  color: "var(--sp-ink-3)",
                  maxWidth: 240,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}>
                  {row[ci] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Text viewer ───────────────────────────────────────────────────────────────

function TextViewer({ text, mimeType }: { text: string; mimeType: string }) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  }, [text]);

  const isCode = mimeType.includes("json") || mimeType.includes("xml")
    || mimeType.includes("javascript") || mimeType.includes("typescript");

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={copy}
        style={{
          position: "absolute", top: 8, right: 8,
          display: "inline-flex", alignItems: "center", gap: 4,
          padding: "4px 9px", borderRadius: 5,
          background: "var(--sp-bg-3)",
          border: "1px solid var(--sp-line-2)",
          color: copied ? "var(--sp-ok)" : "var(--sp-ink-3)",
          fontSize: 10, cursor: "pointer",
          transition: "color 150ms",
          zIndex: 1,
        }}
      >
        {copied ? <Check size={11} /> : <Copy size={11} />}
        {copied ? "Copied" : "Copy"}
      </button>
      <pre style={{
        margin: 0,
        padding: "14px 14px 14px 14px",
        fontSize: 11.5,
        lineHeight: 1.65,
        color: "var(--sp-ink-2)",
        fontFamily: "'Geist Mono', 'Cascadia Code', ui-monospace, monospace",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        overflowY: "auto",
        maxHeight: "55vh",
        background: isCode ? "rgba(0,0,0,0.2)" : "transparent",
        borderRadius: isCode ? 8 : 0,
        tabSize: 2,
      }}>
        {text}
      </pre>
    </div>
  );
}

// ─── Main modal ────────────────────────────────────────────────────────────────

export default function DriveFileModal({ file, onClose }: DriveFileModalProps) {
  const { user } = useAppSelector((s) => s.auth);
  const [data, setData] = useState<FileData | null>(null);
  const [fetching, setFetching] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const missingIds = !user?._id || !file.id;
  const loading = !missingIds && fetching;
  const error = missingIds ? "Missing user or file ID" : fetchError;

  // Close on Escape
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  // Fetch file content
  useEffect(() => {
    // The parent keys this modal by file id, so state starts fresh for every file.
    if (!user?._id || !file.id) return;
    const apiBase = getApiBase();
    const url = `${apiBase}/drive/read?user_id=${encodeURIComponent(user._id)}&file_id=${encodeURIComponent(file.id)}`;

    fetch(url)
      .then(r => r.json())
      .then((d: FileData) => {
        if (!d.success && d.error) throw new Error(d.error);
        setData(d);
      })
      .catch(e => setFetchError(e?.message || "Failed to load file"))
      .finally(() => setFetching(false));
  }, [file.id, user?._id]);

  const FileIcon = file.type === "folder" ? FolderOpen
    : file.mime_type.startsWith("image/") ? ImageIcon
    : FileText;

  const iconColor = file.mime_type === "application/pdf" ? "#c97164"
    : file.mime_type.includes("spreadsheet") || file.mime_type.includes("excel") ? "#4caf7d"
    : file.mime_type.includes("presentation") ? "#d4a04a"
    : "#87a7c4";

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 9800,
        background: "rgba(0,0,0,0.65)",
        display: "flex", alignItems: "center", justifyContent: "center",
        backdropFilter: "blur(6px)",
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: "min(820px, 92vw)",
          maxHeight: "88vh",
          display: "flex", flexDirection: "column",
          background: "var(--sp-bg-2)",
          border: "1px solid var(--sp-line-2)",
          borderRadius: 14,
          boxShadow: "0 28px 72px rgba(0,0,0,0.6)",
          overflow: "hidden",
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div style={{
          padding: "14px 16px",
          display: "flex", alignItems: "center", gap: 10,
          borderBottom: "1px solid var(--sp-line)",
          flexShrink: 0,
          background: "var(--sp-bg)",
        }}>
          <div style={{
            width: 32, height: 32, borderRadius: 7,
            background: `${iconColor}1a`,
            display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
          }}>
            <FileIcon size={16} style={{ color: iconColor }} />
          </div>

          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "var(--sp-ink)", lineHeight: 1.3 }}>
              {file.name}
            </p>
            <p className="sp-mono" style={{ margin: 0, fontSize: 10, color: "var(--sp-ink-4)", marginTop: 2 }}>
              {data?.size_bytes ? formatSize(data.size_bytes) : file.size_bytes ? formatSize(file.size_bytes) : ""}
              {data?.mime_type && ` · ${data.mime_type}`}
            </p>
          </div>

          {/* Open in Drive fallback */}
          {file.link && (
            <a
              href={file.link}
              target="_blank"
              rel="noreferrer"
              style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "5px 10px", borderRadius: 6,
                background: "var(--sp-bg-3)",
                border: "1px solid var(--sp-line)",
                color: "var(--sp-ink-3)",
                fontSize: 11, textDecoration: "none",
                flexShrink: 0,
              }}
            >
              <ExternalLink size={11} /> Open in Drive
            </a>
          )}

          <button
            onClick={onClose}
            style={{
              background: "transparent", border: 0, cursor: "pointer",
              color: "var(--sp-ink-4)", display: "flex", padding: 4, flexShrink: 0,
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* ── Body ── */}
        <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
          {loading && (
            <div style={{
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", gap: 12,
              padding: "60px 24px",
              color: "var(--sp-ink-4)",
            }}>
              <Loader2 size={22} className="animate-spin" style={{ color: "var(--sp-accent)" }} />
              <span className="sp-mono" style={{ fontSize: 12 }}>Reading file from Drive…</span>
            </div>
          )}

          {!loading && error && (
            <div style={{
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", gap: 10,
              padding: "48px 24px", textAlign: "center",
            }}>
              <AlertTriangle size={20} style={{ color: "var(--sp-warn)" }} />
              <p style={{ margin: 0, fontSize: 13, color: "var(--sp-err)" }}>{error}</p>
              {file.link && (
                <a
                  href={file.link} target="_blank" rel="noreferrer"
                  style={{
                    marginTop: 8,
                    display: "inline-flex", alignItems: "center", gap: 5,
                    padding: "6px 13px", borderRadius: 7,
                    background: "var(--sp-accent)", color: "#1a1208",
                    fontSize: 12, fontWeight: 600, textDecoration: "none",
                  }}
                >
                  <ExternalLink size={11} /> Open in Drive instead
                </a>
              )}
            </div>
          )}

          {!loading && !error && data && (
            <>
              {/* Truncation notice */}
              {data.truncated && (
                <div style={{
                  padding: "8px 16px",
                  background: "rgba(217,119,87,0.07)",
                  borderBottom: "1px solid var(--sp-line)",
                  display: "flex", alignItems: "center", gap: 6,
                  fontSize: 11, color: "var(--sp-warn)",
                }}>
                  <AlertTriangle size={12} />
                  File is large — showing first 80 KB. Use "Open in Drive" for the full version.
                </div>
              )}
              {data.note && (
                <div style={{
                  padding: "8px 16px",
                  borderBottom: "1px solid var(--sp-line)",
                  fontSize: 11, color: "var(--sp-ink-4)",
                }}>
                  {data.note}
                </div>
              )}

              {/* Text content */}
              {(data.content_type === "text") && data.content && (
                <TextViewer text={data.content} mimeType={data.mime_type} />
              )}

              {/* CSV table */}
              {data.content_type === "csv" && data.content && (
                <CsvTable csv={data.content} />
              )}

              {/* Image */}
              {data.content_type === "image" && data.content && (
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  padding: 20,
                  background: "rgba(0,0,0,0.2)",
                }}>
                  <img
                    src={`data:${data.mime_type};base64,${data.content}`}
                    alt={data.name}
                    style={{
                      maxWidth: "100%",
                      maxHeight: "60vh",
                      borderRadius: 8,
                      boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
                    }}
                  />
                </div>
              )}

              {/* Binary / unsupported */}
              {data.content_type === "binary" && (
                <div style={{
                  display: "flex", flexDirection: "column",
                  alignItems: "center", justifyContent: "center",
                  gap: 14, padding: "56px 24px", textAlign: "center",
                }}>
                  <div style={{
                    width: 56, height: 56, borderRadius: 12,
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid var(--sp-line)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <File size={24} style={{ color: "var(--sp-ink-4)" }} />
                  </div>
                  <div>
                    <p style={{ margin: 0, fontSize: 14, color: "var(--sp-ink-2)", fontWeight: 500 }}>
                      Can't preview this file type
                    </p>
                    <p className="sp-mono" style={{ margin: "4px 0 0", fontSize: 11, color: "var(--sp-ink-4)" }}>
                      {data.mime_type} · {formatSize(data.size_bytes)}
                    </p>
                  </div>
                  {(data.link || file.link) && (
                    <a
                      href={data.link || file.link} target="_blank" rel="noreferrer"
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 6,
                        padding: "8px 16px", borderRadius: 8,
                        background: "var(--sp-accent)", color: "#1a1208",
                        fontSize: 12, fontWeight: 600, textDecoration: "none",
                      }}
                    >
                      <ExternalLink size={13} /> Open in Drive
                    </a>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
