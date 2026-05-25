import React, { useState } from "react";
import { Search, Globe, X, ExternalLink } from "lucide-react";

export interface SearchResult {
  title: string;
  url: string;
  snippet: string;
  favicon?: { google?: string; duckduckgo?: string };
  _relevance_score?: number;
}

export interface WebSearchData {
  query: string;
  results: SearchResult[];
  total_results: number;
  search_time_ms?: number;
}

interface WebSearchCardsProps {
  data: WebSearchData;
  onDismiss?: () => void;
}

function domain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function FaviconImg({ result }: { result: SearchResult }) {
  const src = result.favicon?.google || result.favicon?.duckduckgo || "";
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return <Globe size={13} style={{ color: "var(--sp-ink-4)", flexShrink: 0 }} />;
  }
  return (
    <img
      src={src}
      alt=""
      width={13}
      height={13}
      style={{ borderRadius: 2, flexShrink: 0 }}
      onError={() => setFailed(true)}
    />
  );
}

function ResultRow({ result, index }: { result: SearchResult; index: number }) {
  const [hovered, setHovered] = useState(false);
  const d = domain(result.url);

  return (
    <a
      href={result.url}
      target="_blank"
      rel="noreferrer"
      style={{ textDecoration: "none" }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div style={{
        padding: "10px 14px",
        borderRadius: 8,
        background: hovered ? "var(--sp-bg-3)" : "transparent",
        border: `1px solid ${hovered ? "var(--sp-line-2)" : "transparent"}`,
        transition: "background 120ms, border-color 120ms",
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        cursor: "pointer",
      }}>
        {/* Index */}
        <span className="sp-mono" style={{
          fontSize: 10, color: "var(--sp-ink-4)", minWidth: 16,
          lineHeight: "18px", flexShrink: 0,
        }}>
          {index + 1}
        </span>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Title row */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
            <FaviconImg result={result} />
            <p style={{
              margin: 0, fontSize: 12.5, fontWeight: 600,
              color: "var(--sp-ink)", lineHeight: 1.35,
              overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis",
            }}>
              {result.title}
            </p>
            {hovered && <ExternalLink size={10} style={{ color: "var(--sp-ink-4)", flexShrink: 0 }} />}
          </div>

          {/* Domain */}
          <p className="sp-mono" style={{
            margin: "0 0 4px", fontSize: 10, color: "var(--sp-accent)",
          }}>
            {d}
          </p>

          {/* Snippet */}
          <p style={{
            margin: 0, fontSize: 11.5, color: "var(--sp-ink-3)",
            lineHeight: 1.55,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}>
            {result.snippet}
          </p>
        </div>
      </div>
    </a>
  );
}

const INITIAL_SHOW = 5;

export default function WebSearchCards({ data, onDismiss }: WebSearchCardsProps) {
  const [showAll, setShowAll] = useState(false);
  if (!data?.results?.length) return null;

  const visible = showAll ? data.results : data.results.slice(0, INITIAL_SHOW);
  const hasMore = data.results.length > INITIAL_SHOW;

  return (
    <div style={{
      borderRadius: 12,
      border: "1px solid var(--sp-line)",
      overflow: "hidden",
      background: "var(--sp-bg-2)",
    }}>
      {/* Header */}
      <div style={{
        padding: "10px 14px",
        display: "flex", alignItems: "center", gap: 8,
        borderBottom: "1px solid var(--sp-line)",
      }}>
        <Search size={12} style={{ color: "var(--sp-accent)", flexShrink: 0 }} />
        <span className="sp-mono" style={{ fontSize: 11.5, color: "var(--sp-ink)", fontWeight: 500, flex: 1, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
          {data.query}
        </span>
        <span style={{ width: 6, height: 6, borderRadius: 99, background: "var(--sp-ok)", flexShrink: 0 }} />
        <span className="sp-mono" style={{ fontSize: 10.5, color: "var(--sp-ink-4)", flexShrink: 0 }}>
          {data.total_results} result{data.total_results !== 1 ? "s" : ""}
          {data.search_time_ms != null ? ` · ${Math.round(data.search_time_ms)}ms` : ""}
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

      {/* Result list */}
      <div style={{ padding: "6px 4px" }}>
        {visible.map((r, i) => (
          <ResultRow key={r.url} result={r} index={i} />
        ))}
      </div>

      {/* Show more */}
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
            {showAll ? "Show less" : `Show ${data.results.length - INITIAL_SHOW} more results`}
          </button>
        </div>
      )}
    </div>
  );
}
