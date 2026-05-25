import React, { useState, useEffect, useCallback } from "react";
import {
  X, Star, MapPin, ExternalLink, DollarSign,
  Navigation, Phone, ChevronLeft, ChevronRight,
} from "lucide-react";

export interface EntityCardData {
  type?: string;
  name: string;
  price_per_night?: string;
  price?: string;
  price_range?: string;
  rating?: number;
  review_count?: number;
  location?: string;
  address?: string;
  amenities?: string[];
  features?: string[];
  images?: string[];
  booking_url?: string;
  buy_url?: string;
  menu_url?: string;
  website?: string;
  maps_url?: string;
  description?: string;
  cuisine?: string;
  brand?: string;
  _score?: number;
  // Place/business fields
  distance?: string;
  hours?: string;
  open_now?: boolean;
  phone?: string;
  type_label?: string;
}

interface EntityCardsProps {
  entities: EntityCardData[];
  intent?: string;
  onDismiss: () => void;
}

// ─── Radial decorative background ─────────────────────────────────────────────

function RadialBg() {
  return (
    <svg
      viewBox="0 0 260 260"
      style={{
        position: "absolute",
        right: -50, bottom: -50,
        width: 260, height: 260,
        pointerEvents: "none",
        opacity: 0.7,
      }}
    >
      {[18, 38, 65, 95, 132, 172, 215].map((r, i) => (
        <circle
          key={i}
          cx={260} cy={260}
          r={r}
          fill="none"
          stroke="rgba(217,119,87,0.25)"
          strokeWidth={i === 0 ? 2 : 0.75}
        />
      ))}
      <circle cx={260} cy={260} r={5} fill="rgba(217,119,87,0.55)" />
      <circle cx={260} cy={260} r={14} fill="none" stroke="rgba(217,119,87,0.4)" strokeWidth={1.5} />
    </svg>
  );
}

// ─── Image gallery (for detail modal) ─────────────────────────────────────────

function ImageGallery({ images, name }: { images: string[]; name: string }) {
  const [idx, setIdx] = useState(0);
  const [errors, setErrors] = useState<Set<number>>(new Set());

  const prev = useCallback(() => {
    let n = idx - 1;
    while (n >= 0 && errors.has(n)) n--;
    if (n >= 0) setIdx(n);
  }, [idx, errors]);

  const next = useCallback(() => {
    let n = idx + 1;
    while (n < images.length && errors.has(n)) n++;
    if (n < images.length) setIdx(n);
  }, [idx, images.length, errors]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") prev();
      if (e.key === "ArrowRight") next();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [prev, next]);

  if (!images[idx] || errors.has(idx)) return null;
  const valid = images.filter((_, i) => !errors.has(i));

  return (
    <div style={{ position: "relative", height: 220, overflow: "hidden", background: "#0a0a0a" }}>
      <img
        src={images[idx]}
        alt={name}
        referrerPolicy="no-referrer"
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
        onError={() => setErrors(p => new Set(p).add(idx))}
      />
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to top, rgba(0,0,0,0.7) 0%, transparent 50%)" }} />
      {valid.length > 1 && (
        <>
          <button
            onClick={e => { e.stopPropagation(); prev(); }}
            style={{
              position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)",
              background: "rgba(0,0,0,0.5)", border: 0, borderRadius: 99,
              padding: 6, cursor: "pointer", color: "#fff", display: "flex",
            }}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            onClick={e => { e.stopPropagation(); next(); }}
            style={{
              position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
              background: "rgba(0,0,0,0.5)", border: 0, borderRadius: 99,
              padding: 6, cursor: "pointer", color: "#fff", display: "flex",
            }}
          >
            <ChevronRight size={16} />
          </button>
          <div style={{
            position: "absolute", bottom: 10, left: "50%", transform: "translateX(-50%)",
            display: "flex", gap: 5,
          }}>
            {images.map((_, i) => !errors.has(i) && (
              <button
                key={i}
                onClick={e => { e.stopPropagation(); setIdx(i); }}
                style={{
                  width: 7, height: 7, borderRadius: 99, border: 0, cursor: "pointer",
                  background: i === idx ? "#fff" : "rgba(255,255,255,0.3)",
                  padding: 0,
                }}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ─── Detail modal ──────────────────────────────────────────────────────────────

function EntityDetailModal({ entity, onClose }: { entity: EntityCardData; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const externalUrl = entity.booking_url || entity.buy_url || entity.menu_url || entity.website;
  const mapsUrl = entity.maps_url ||
    ((entity.address || entity.location)
      ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${entity.name} ${entity.address || entity.location}`)}`
      : "");
  const tags = entity.amenities || entity.features || [];
  const price = entity.price_per_night || entity.price || entity.price_range;

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 9500,
        background: "rgba(0,0,0,0.65)",
        display: "flex", alignItems: "center", justifyContent: "center",
        backdropFilter: "blur(6px)",
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: "100%", maxWidth: 480,
          maxHeight: "88vh", overflowY: "auto",
          background: "var(--sp-bg-2)",
          border: "1px solid var(--sp-line-2)",
          borderRadius: 16,
          boxShadow: "0 24px 64px rgba(0,0,0,0.55)",
          position: "relative",
          overflow: "hidden",
        }}
        onClick={e => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          style={{
            position: "absolute", top: 12, right: 12, zIndex: 10,
            background: "rgba(0,0,0,0.45)", border: 0, borderRadius: 99,
            padding: 6, cursor: "pointer", color: "var(--sp-ink-3)", display: "flex",
          }}
        >
          <X size={15} />
        </button>

        {entity.images && entity.images.length > 0 && (
          <ImageGallery images={entity.images} name={entity.name} />
        )}

        <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--sp-ink)", lineHeight: 1.2 }}>
                {entity.name}
              </h2>
              {entity.brand && (
                <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-accent)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                  {entity.brand}
                </span>
              )}
              {entity.type_label && (
                <p style={{ margin: "3px 0 0", fontSize: 11, color: "var(--sp-ink-4)" }}>{entity.type_label}</p>
              )}
            </div>
            {price && (
              <span style={{
                fontSize: 13, fontWeight: 600, color: "#4caf7d",
                background: "rgba(76,175,125,0.12)",
                padding: "4px 10px", borderRadius: 6, flexShrink: 0,
              }}>
                {price}
              </span>
            )}
          </div>

          {entity.rating != null && (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <Star size={14} style={{ fill: "#f59e0b", color: "#f59e0b" }} />
                <span style={{ fontSize: 14, fontWeight: 600, color: "var(--sp-ink)" }}>
                  {entity.rating.toFixed(1)}
                </span>
              </span>
              {entity.review_count != null && (
                <span style={{ fontSize: 13, color: "var(--sp-ink-4)" }}>
                  ({entity.review_count.toLocaleString()} reviews)
                </span>
              )}
            </div>
          )}

          {(entity.open_now != null || entity.hours || entity.distance) && (
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              {entity.open_now != null && (
                <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
                  <span style={{ width: 6, height: 6, borderRadius: 99, background: entity.open_now ? "var(--sp-ok)" : "var(--sp-err)" }} />
                  <span style={{ color: entity.open_now ? "var(--sp-ok)" : "var(--sp-err)" }}>
                    {entity.open_now ? "Open" : "Closed"}
                  </span>
                </span>
              )}
              {entity.hours && (
                <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)" }}>{entity.hours}</span>
              )}
              {entity.distance && (
                <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)" }}>{entity.distance}</span>
              )}
            </div>
          )}

          {(entity.address || entity.location) && (
            <p style={{ margin: 0, display: "flex", alignItems: "flex-start", gap: 6, fontSize: 13, color: "var(--sp-ink-3)" }}>
              <MapPin size={14} style={{ color: "var(--sp-accent)", marginTop: 1, flexShrink: 0 }} />
              {entity.address || entity.location}
            </p>
          )}

          {entity.description && (
            <p style={{ margin: 0, fontSize: 13, color: "var(--sp-ink-3)", lineHeight: 1.6 }}>
              {entity.description}
            </p>
          )}

          {entity.cuisine && (
            <p className="sp-mono" style={{ margin: 0, fontSize: 11, color: "var(--sp-ink-4)" }}>
              Cuisine: {entity.cuisine}
            </p>
          )}

          {tags.length > 0 && (
            <div>
              <p className="sp-mono" style={{ margin: "0 0 8px", fontSize: 10, color: "var(--sp-ink-4)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                Features
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {tags.map((t, i) => (
                  <span key={i} style={{
                    fontSize: 11, color: "var(--sp-ink-3)",
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid var(--sp-line)",
                    padding: "3px 8px", borderRadius: 4,
                  }}>
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: 8, paddingTop: 6, borderTop: "1px solid var(--sp-line)" }}>
            {mapsUrl && (
              <a href={mapsUrl} target="_blank" rel="noreferrer" style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "7px 13px", borderRadius: 7,
                background: "var(--sp-accent)", color: "#1a1208",
                fontSize: 12, fontWeight: 600, textDecoration: "none",
              }}>
                <Navigation size={12} /> Get directions
              </a>
            )}
            {entity.phone && (
              <a href={`tel:${entity.phone}`} style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "7px 12px", borderRadius: 7,
                background: "var(--sp-bg-3)", border: "1px solid var(--sp-line-2)",
                color: "var(--sp-ink-2)", fontSize: 12, textDecoration: "none",
              }}>
                <Phone size={12} /> Call
              </a>
            )}
            {externalUrl && (
              <a href={externalUrl} target="_blank" rel="noreferrer" style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "7px 12px", borderRadius: 7,
                background: "var(--sp-bg-3)", border: "1px solid var(--sp-line)",
                color: "var(--sp-ink-3)", fontSize: 12, textDecoration: "none",
              }}>
                <ExternalLink size={12} /> View
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Featured left panel ───────────────────────────────────────────────────────

function FeaturedPanel({
  entity, rank, onOpenDetail,
}: {
  entity: EntityCardData;
  rank: number;
  onOpenDetail: () => void;
}) {
  const [imgError, setImgError] = useState(false);
  const hasImg = !!(entity.images?.[0] && !imgError);
  const price = entity.price_per_night || entity.price || entity.price_range;
  const tags = entity.amenities || entity.features || [];
  const externalUrl = entity.booking_url || entity.website || entity.buy_url || entity.menu_url;
  const mapsUrl = entity.maps_url ||
    ((entity.address || entity.location)
      ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${entity.name} ${entity.address || entity.location}`)}`
      : "");

  return (
    <div
      onClick={onOpenDetail}
      style={{
        flex: "0 0 55%",
        position: "relative", overflow: "hidden",
        padding: "18px 16px 16px",
        borderRight: "1px solid var(--sp-line)",
        display: "flex", flexDirection: "column", gap: 10,
        minHeight: 280,
        cursor: "pointer",
        background: "var(--sp-bg)",
      }}
    >
      {/* Background */}
      {hasImg ? (
        <>
          <img
            src={entity.images![0]}
            alt={entity.name}
            onError={() => setImgError(true)}
            referrerPolicy="no-referrer"
            style={{
              position: "absolute", inset: 0,
              width: "100%", height: "100%",
              objectFit: "cover", opacity: 0.35,
            }}
          />
          <div style={{
            position: "absolute", inset: 0,
            background: "linear-gradient(130deg, var(--sp-bg) 15%, rgba(0,0,0,0.35) 100%)",
          }} />
        </>
      ) : (
        <RadialBg />
      )}

      {/* Content */}
      <div style={{ position: "relative", zIndex: 1, display: "flex", flexDirection: "column", gap: 9, flex: 1 }}>

        {/* Rank + type badges */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{
            fontSize: 10, fontWeight: 700,
            color: "#1a1208", background: "var(--sp-accent)",
            padding: "2px 7px", borderRadius: 4,
          }}>
            #{rank}
          </span>
          {(entity.type_label || entity.type) && (
            <span className="sp-mono" style={{
              fontSize: 10, color: "var(--sp-ink-4)",
              background: "rgba(255,255,255,0.05)",
              border: "1px solid var(--sp-line)",
              padding: "2px 7px", borderRadius: 4,
            }}>
              {entity.type_label || entity.type}
            </span>
          )}
          {entity.brand && (
            <span className="sp-mono" style={{
              fontSize: 10, color: "var(--sp-accent)",
              textTransform: "uppercase", letterSpacing: "0.06em",
            }}>
              {entity.brand}
            </span>
          )}
        </div>

        {/* Name */}
        <h3 style={{
          margin: 0, fontSize: 19, fontWeight: 700,
          color: "var(--sp-ink)", lineHeight: 1.2, letterSpacing: "-0.02em",
        }}>
          {entity.name}
        </h3>

        {/* Rating · open status · hours · distance */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {entity.rating != null && (
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <Star size={12} style={{ fill: "#f59e0b", color: "#f59e0b" }} />
              <span className="sp-mono" style={{ fontSize: 12, color: "var(--sp-ink)", fontWeight: 500 }}>
                {entity.rating.toFixed(1)}
              </span>
              {entity.review_count != null && (
                <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>
                  ({entity.review_count.toLocaleString()})
                </span>
              )}
            </span>
          )}
          {entity.open_now != null && (
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <span style={{
                width: 5, height: 5, borderRadius: 99,
                background: entity.open_now ? "var(--sp-ok)" : "var(--sp-err)",
              }} />
              <span className="sp-mono" style={{
                fontSize: 11,
                color: entity.open_now ? "var(--sp-ok)" : "var(--sp-err)",
              }}>
                {entity.open_now ? "Open" : "Closed"}
              </span>
            </span>
          )}
          {entity.hours && (
            <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)" }}>
              {entity.hours}
            </span>
          )}
          {entity.distance && (
            <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)", marginLeft: "auto" }}>
              {entity.distance}
            </span>
          )}
          {price && !entity.distance && (
            <span style={{
              fontSize: 11, fontWeight: 600, color: "#4caf7d",
              background: "rgba(76,175,125,0.12)",
              padding: "1px 7px", borderRadius: 4,
            }}>
              {price}
            </span>
          )}
        </div>

        {/* Address */}
        {(entity.address || entity.location) && (
          <div style={{ display: "flex", alignItems: "flex-start", gap: 5 }}>
            <MapPin size={11} style={{ color: "var(--sp-accent)", marginTop: 1, flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: "var(--sp-ink-3)", lineHeight: 1.35 }}>
              {entity.address || entity.location}
            </span>
          </div>
        )}

        {/* Description (if no address) */}
        {entity.description && !(entity.address || entity.location) && (
          <p style={{ margin: 0, fontSize: 12, color: "var(--sp-ink-3)", lineHeight: 1.5 }}>
            {entity.description.slice(0, 110)}{entity.description.length > 110 ? "…" : ""}
          </p>
        )}

        {/* Cuisine */}
        {entity.cuisine && (
          <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>
            {entity.cuisine}
          </span>
        )}

        {/* Tag chips */}
        {tags.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {tags.slice(0, 4).map((tag, i) => (
              <span key={i} style={{
                fontSize: 10, color: "var(--sp-ink-3)",
                background: "rgba(255,255,255,0.05)",
                border: "1px solid var(--sp-line)",
                padding: "2px 7px", borderRadius: 4,
              }}>
                {tag}
              </span>
            ))}
          </div>
        )}

        {/* Action buttons — stop propagation so they don't open modal */}
        <div
          style={{ marginTop: "auto", display: "flex", alignItems: "center", gap: 6 }}
          onClick={e => e.stopPropagation()}
        >
          {mapsUrl && (
            <a
              href={mapsUrl} target="_blank" rel="noreferrer"
              style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "6px 11px", borderRadius: 7,
                background: "var(--sp-accent)", color: "#1a1208",
                fontSize: 11, fontWeight: 600, textDecoration: "none",
              }}
            >
              <Navigation size={11} /> Get directions
            </a>
          )}
          {entity.phone && (
            <a
              href={`tel:${entity.phone}`}
              style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "6px 10px", borderRadius: 7,
                background: "var(--sp-bg-3)", border: "1px solid var(--sp-line-2)",
                color: "var(--sp-ink-2)", fontSize: 11, textDecoration: "none",
              }}
            >
              <Phone size={11} /> Call
            </a>
          )}
          {externalUrl && (
            <a
              href={externalUrl} target="_blank" rel="noreferrer"
              style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 30, height: 30, borderRadius: 7,
                background: "var(--sp-bg-3)", border: "1px solid var(--sp-line)",
                color: "var(--sp-ink-4)", textDecoration: "none",
              }}
            >
              <ExternalLink size={11} />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Entity list (right panel) ────────────────────────────────────────────────

function EntityList({
  entities, activeIdx, onSelect,
}: {
  entities: EntityCardData[];
  activeIdx: number;
  onSelect: (i: number) => void;
}) {
  return (
    <div style={{ flex: 1, overflowY: "auto", maxHeight: 340, background: "var(--sp-bg-2)" }}>
      {entities.map((entity, i) => {
        const isActive = i === activeIdx;
        return (
          <div
            key={i}
            onClick={() => onSelect(i)}
            style={{
              display: "flex", alignItems: "flex-start", gap: 10,
              padding: "11px 14px",
              borderBottom: i < entities.length - 1 ? "1px solid var(--sp-line)" : "none",
              background: isActive ? "rgba(217,119,87,0.07)" : "transparent",
              cursor: "pointer",
              transition: "background 120ms",
            }}
            onMouseEnter={e => {
              if (!isActive) (e.currentTarget as HTMLDivElement).style.background = "rgba(255,255,255,0.02)";
            }}
            onMouseLeave={e => {
              if (!isActive) (e.currentTarget as HTMLDivElement).style.background = "transparent";
            }}
          >
            {/* Rank */}
            <span style={{
              fontSize: 14, fontWeight: 700,
              color: isActive ? "var(--sp-accent)" : "var(--sp-ink-4)",
              minWidth: 18, flexShrink: 0, paddingTop: 1,
            }}>
              {i + 1}
            </span>

            {/* Info */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{
                margin: 0, fontSize: 12, fontWeight: 500, lineHeight: 1.3,
                color: isActive ? "var(--sp-ink)" : "var(--sp-ink-2)",
              }}>
                {entity.name}
              </p>
              {(entity.address || entity.location) && (
                <p className="sp-mono" style={{
                  margin: "2px 0 0", fontSize: 10, color: "var(--sp-ink-4)",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {entity.address || entity.location}
                </p>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
                {entity.rating != null && (
                  <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                    <Star size={9} style={{ fill: "#f59e0b", color: "#f59e0b" }} />
                    <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-3)" }}>
                      {entity.rating.toFixed(1)}
                    </span>
                  </span>
                )}
                {entity.open_now != null && (
                  <span style={{ display: "flex", alignItems: "center", gap: 2 }}>
                    <span style={{
                      width: 4, height: 4, borderRadius: 99,
                      background: entity.open_now ? "var(--sp-ok)" : "var(--sp-err)",
                    }} />
                    <span className="sp-mono" style={{
                      fontSize: 10,
                      color: entity.open_now ? "var(--sp-ok)" : "var(--sp-err)",
                    }}>
                      {entity.open_now ? "Open" : "Closed"} {entity.hours}
                    </span>
                  </span>
                )}
              </div>
            </div>

            {/* Distance */}
            {entity.distance && (
              <span className="sp-mono" style={{
                fontSize: 10, color: "var(--sp-ink-4)",
                flexShrink: 0, paddingTop: 1,
              }}>
                {entity.distance}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────

export default function EntityCards({ entities, intent, onDismiss }: EntityCardsProps) {
  const [featuredIdx, setFeaturedIdx] = useState(0);
  const [showModal, setShowModal] = useState(false);

  if (!entities?.length) return null;

  const featured = entities[featuredIdx];
  const label = intent
    ? intent.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())
    : "Results";

  // Derive "near City" hint from first entity's location
  const nearCity = entities[0]?.location?.split(",")[0]?.trim()
    || entities[0]?.address?.split(",").slice(-2, -1)[0]?.trim();

  const mapsSearchUrl = nearCity || featured?.name
    ? `https://www.google.com/maps/search/${encodeURIComponent(`${label} ${nearCity || ""}`.trim())}`
    : null;

  return (
    <>
      <div style={{
        borderRadius: 12,
        border: "1px solid var(--sp-line)",
        overflow: "hidden",
        background: "var(--sp-bg-2)",
      }}>
        {/* Header */}
        <div style={{
          padding: "11px 14px",
          display: "flex", alignItems: "center", gap: 8,
          borderBottom: "1px solid var(--sp-line)",
        }}>
          <MapPin size={13} style={{ color: "var(--sp-accent)", flexShrink: 0 }} />
          <span style={{ fontSize: 12, fontWeight: 500, color: "var(--sp-ink)" }}>{label}</span>
          <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>
            · {entities.length} found{nearCity ? ` near ${nearCity}` : ""}
          </span>
          <div style={{ flex: 1 }} />
          {mapsSearchUrl && (
            <a
              href={mapsSearchUrl}
              target="_blank"
              rel="noreferrer"
              style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                fontSize: 11, color: "var(--sp-ink-3)",
                background: "var(--sp-bg-3)",
                border: "1px solid var(--sp-line)",
                padding: "3px 9px", borderRadius: 5,
                textDecoration: "none",
              }}
            >
              Map
            </a>
          )}
          <button
            onClick={onDismiss}
            style={{
              background: "transparent", border: 0, cursor: "pointer",
              color: "var(--sp-ink-4)", display: "flex", padding: 2,
            }}
          >
            <X size={13} />
          </button>
        </div>

        {/* Split body */}
        <div style={{ display: "flex" }}>
          <FeaturedPanel
            entity={featured}
            rank={featuredIdx + 1}
            onOpenDetail={() => setShowModal(true)}
          />
          <EntityList
            entities={entities}
            activeIdx={featuredIdx}
            onSelect={setFeaturedIdx}
          />
        </div>
      </div>

      {showModal && (
        <EntityDetailModal entity={featured} onClose={() => setShowModal(false)} />
      )}
    </>
  );
}
