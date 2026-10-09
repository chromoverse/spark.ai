import React, { useState } from "react";
import { File, FileText, FolderOpen, Image as ImageIcon, X, type LucideIcon } from "lucide-react";
import DriveFileModal from "./DriveFileModal";

export interface DriveFile {
  id: string;
  name: string;
  type: "file" | "folder";
  mime_type: string;
  modified?: string;
  size_bytes?: number;
  link?: string;
}

interface DriveFileCardsProps {
  files: DriveFile[];
  label?: string;
  onDismiss?: () => void;
}

type FileStyle = { Icon: LucideIcon; color: string; bg: string };

function getFileStyle(mimeType: string, fileType: string): FileStyle {
  if (fileType === "folder")
    return { Icon: FolderOpen, color: "#d97757", bg: "rgba(217,119,87,0.14)" };
  if (mimeType.startsWith("image/"))
    return { Icon: ImageIcon, color: "#87a7c4", bg: "rgba(135,167,196,0.12)" };
  if (mimeType === "application/pdf")
    return { Icon: FileText, color: "#c97164", bg: "rgba(201,113,100,0.13)" };
  if (mimeType.includes("spreadsheet") || mimeType.includes("excel"))
    return { Icon: FileText, color: "#4caf7d", bg: "rgba(76,175,125,0.13)" };
  if (mimeType.includes("presentation") || mimeType.includes("powerpoint"))
    return { Icon: FileText, color: "#d4a04a", bg: "rgba(212,160,74,0.13)" };
  if (mimeType.includes("document") || mimeType.includes("word"))
    return { Icon: FileText, color: "#87a7c4", bg: "rgba(135,167,196,0.12)" };
  return { Icon: File, color: "var(--sp-ink-3)", bg: "rgba(255,255,255,0.06)" };
}

function formatSize(bytes?: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 86_400_000) return "Today";
  if (diff < 172_800_000) return "Yesterday";
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  if (diff < 7 * 86_400_000) return days[d.getDay()];
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function FileCard({ file, onOpen }: { file: DriveFile; onOpen: () => void }) {
  const [hovered, setHovered] = useState(false);
  const { Icon, color, bg } = getFileStyle(file.mime_type, file.type);
  const nameParts = file.name.split(".");
  const ext = nameParts.length > 1 ? nameParts.pop()!.toUpperCase() : null;
  const meta = [formatSize(file.size_bytes), formatDate(file.modified)].filter(Boolean).join(" · ");

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onOpen}
      style={{
        display: "flex", flexDirection: "column", gap: 8,
        padding: "13px 12px 11px",
        borderRadius: 9,
        background: hovered ? "var(--sp-bg-3)" : "var(--sp-bg)",
        border: `1px solid ${hovered ? "var(--sp-line-2)" : "var(--sp-line)"}`,
        transition: "border-color 150ms, background 150ms",
        position: "relative", overflow: "hidden",
        cursor: "pointer",
        height: "100%", boxSizing: "border-box",
      }}
    >
      {/* hover glow */}
      <div style={{
        position: "absolute", inset: 0,
        background: `radial-gradient(ellipse at 100% 100%, ${bg} 0%, transparent 60%)`,
        opacity: hovered ? 1 : 0,
        transition: "opacity 200ms",
        pointerEvents: "none",
      }} />

      {/* icon */}
      <div style={{
        width: 36, height: 36, borderRadius: 8,
        background: bg,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0,
      }}>
        <Icon size={17} style={{ color }} />
      </div>

      {/* name */}
      <p style={{
        margin: 0, fontSize: 11.5, fontWeight: 500,
        color: "var(--sp-ink)", lineHeight: 1.4,
        overflow: "hidden",
        display: "-webkit-box",
        WebkitLineClamp: 2,
        WebkitBoxOrient: "vertical",
        wordBreak: "break-word",
      }}>
        {file.name}
      </p>

      {/* meta + ext */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 4 }}>
        {meta && (
          <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)" }}>
            {meta}
          </span>
        )}
        {ext && (
          <span className="sp-mono" style={{
            fontSize: 9, color, background: bg,
            padding: "1px 5px", borderRadius: 3,
            fontWeight: 600, letterSpacing: "0.04em", lineHeight: 1.6,
            marginLeft: "auto",
          }}>
            {ext}
          </span>
        )}
      </div>
    </div>
  );
}

const INITIAL_SHOW = 6;

export default function DriveFileCards({ files, label, onDismiss }: DriveFileCardsProps) {
  const [showAll, setShowAll] = useState(false);
  const [openFile, setOpenFile] = useState<DriveFile | null>(null);
  if (!files?.length) return null;

  const visible = showAll ? files : files.slice(0, INITIAL_SHOW);
  const hasMore = files.length > INITIAL_SHOW;

  return (
    <>
      <div style={{
        borderRadius: 12,
        border: "1px solid var(--sp-line)",
        overflow: "hidden",
        background: "var(--sp-bg-2)",
      }}>
        {/* header */}
        <div style={{
          padding: "11px 14px",
          display: "flex", alignItems: "center", gap: 8,
          borderBottom: "1px solid var(--sp-line)",
        }}>
          <FolderOpen size={13} style={{ color: "var(--sp-accent)", flexShrink: 0 }} />
          <span className="sp-mono" style={{ fontSize: 12, color: "var(--sp-ink)", fontWeight: 500 }}>
            {label || "File Search"}
          </span>
          <span style={{ width: 6, height: 6, borderRadius: 99, background: "var(--sp-ok)", flexShrink: 0 }} />
          <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)", flex: 1 }}>
            {files.length} file{files.length !== 1 ? "s" : ""} found in Google Drive
          </span>
          {onDismiss && (
            <button
              onClick={onDismiss}
              style={{ background: "transparent", border: 0, cursor: "pointer", color: "var(--sp-ink-4)", display: "flex", padding: 2 }}
            >
              <X size={13} />
            </button>
          )}
        </div>

        {/* grid */}
        <div style={{
          padding: 12,
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 8,
        }}>
          {visible.map(file => (
            <FileCard key={file.id} file={file} onOpen={() => setOpenFile(file)} />
          ))}
        </div>

        {/* show more toggle */}
        {hasMore && (
          <div style={{ padding: "0 12px 12px" }}>
            <button
              onClick={() => setShowAll(v => !v)}
              style={{
                width: "100%", padding: "7px 0",
                background: "var(--sp-bg)",
                border: "1px solid var(--sp-line)",
                borderRadius: 7, cursor: "pointer",
                fontSize: 11, color: "var(--sp-ink-4)",
              }}
            >
              {showAll ? "Show less" : `Show ${files.length - INITIAL_SHOW} more files`}
            </button>
          </div>
        )}
      </div>

      {/* Inline file viewer modal */}
      {openFile && (
        <DriveFileModal key={openFile.id} file={openFile} onClose={() => setOpenFile(null)} />
      )}
    </>
  );
}
