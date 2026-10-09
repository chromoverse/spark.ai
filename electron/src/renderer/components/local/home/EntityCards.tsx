import React, { useState, useEffect, useCallback } from "react";
import {
  X, Star, MapPin, ExternalLink,
  Navigation, Phone, ChevronLeft, ChevronRight,
  MessageSquare, User, BookOpen, ShoppingCart, Play,
  Ticket, UtensilsCrossed, Plane,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Review {
  text: string;
  rating?: number;
  author?: string;
  date?: string;
}

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
  reviews?: Review[];
  booking_url?: string;
  buy_url?: string;
  menu_url?: string;
  website?: string;
  maps_url?: string;
  description?: string;
  cuisine?: string;
  brand?: string;
  _score?: number;
  distance?: string;
  hours?: string;
  open_now?: boolean;
  phone?: string;
  type_label?: string;
  // person
  title?: string;
  born?: string;
  nationality?: string;
  known_for?: string;
  bio?: string;
  social_links?: string[];
  // movie / show
  year?: string;
  genre?: string;
  director?: string;
  cast?: string[];
  runtime?: string;
  plot?: string;
  streaming_on?: string[];
  trailer_url?: string;
  // event
  date?: string;
  time?: string;
  venue?: string;
  category?: string;
  // college
  ranking?: string;
  programs?: string[];
  tuition?: string;
  acceptance_rate?: string;
  // flight
  airline?: string;
  departure?: string;
  arrival?: string;
  duration?: string;
  stops?: string;
  aircraft?: string;
  // place (uses location, category, hours, price already above)
  source_url?: string;
}

// Progress for an in-flight (or just-finished) entity-card action, keyed
// by the normalised entity name. The renderer attaches a compact status
// strip to the matching card so the user sees "Reaching payment page…"
// directly under the product they clicked, instead of a separate Browser
// Action card buried elsewhere in the thread.
export interface EntityActionProgress {
  entity_key: string;
  status: "pending" | "running" | "completed" | "failed";
  latest_step: string;
  result_summary?: string;
}

interface EntityCardsProps {
  entities: EntityCardData[];
  intent?: string;
  onDismiss: () => void;
  onAction?: (action: string, entity: EntityCardData) => void;
  entityActions?: EntityActionProgress[];
}

// ── Entity action config ──────────────────────────────────────────────────────

interface EntityAction {
  label: string;
  actionKey: string;
  Icon: React.ComponentType<{ size?: number }>;
}

function getEntityAction(entity: EntityCardData): EntityAction | null {
  const t = (entity.type || "").toLowerCase();
  if (t === "hotel" || t === "hostel" || entity.booking_url)
    return { label: "Book Now", actionKey: "book_hotel", Icon: BookOpen };
  if (t === "restaurant" || t === "cafe" || t === "food" || entity.menu_url)
    return { label: "Reserve", actionKey: "reserve_table", Icon: UtensilsCrossed };
  if (t === "product" || entity.buy_url)
    return { label: "Buy Now", actionKey: "buy_product", Icon: ShoppingCart };
  if (t === "movie" || t === "show" || t === "tv_show")
    return { label: "Watch", actionKey: "play_media", Icon: Play };
  if (t === "event" || t === "concert" || t === "festival")
    return { label: "Get Tickets", actionKey: "book_ticket", Icon: Ticket };
  if (t === "flight")
    return { label: "Book Flight", actionKey: "book_ticket", Icon: Plane };
  return null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getPrice(e: EntityCardData) {
  return e.price_per_night || e.price || e.price_range || e.tuition || null;
}

function getExternalUrl(e: EntityCardData) {
  return e.booking_url || e.buy_url || e.website || e.menu_url || e.trailer_url || e.source_url || null;
}

// ── Generic field display helpers ─────────────────────────────────────────────

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", gap: 8, fontSize: 12, marginBottom: 4 }}>
      <span className="sp-mono" style={{ color: "var(--sp-ink-4)", minWidth: 88, flexShrink: 0 }}>{label}</span>
      <span style={{ color: "var(--sp-ink-3)" }}>{value}</span>
    </div>
  );
}

function TagList({ label, items }: { label: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div style={{ marginBottom: 8 }}>
      <p className="sp-mono" style={{ margin: "0 0 5px", fontSize: 10, color: "var(--sp-ink-4)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {items.map((t, i) => (
          <span key={i} style={{ fontSize: 11, color: "var(--sp-ink-3)", background: "rgba(255,255,255,0.05)", border: "1px solid var(--sp-line)", padding: "2px 7px", borderRadius: 4 }}>{t}</span>
        ))}
      </div>
    </div>
  );
}

function getMapsUrl(e: EntityCardData) {
  if (e.maps_url) return e.maps_url;
  const loc = e.address || e.location;
  if (!loc && !e.name) return null;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${e.name} ${loc || ""}`.trim())}`;
}

// ── Radial decorative bg (used when no image) ─────────────────────────────────

function RadialBg() {
  return (
    <svg viewBox="0 0 260 260" style={{
      position: "absolute", right: -50, bottom: -50,
      width: 260, height: 260, pointerEvents: "none", opacity: 0.7,
    }}>
      {[18, 38, 65, 95, 132, 172, 215].map((r, i) => (
        <circle key={i} cx={260} cy={260} r={r} fill="none"
          stroke="rgba(217,119,87,0.25)" strokeWidth={i === 0 ? 2 : 0.75} />
      ))}
      <circle cx={260} cy={260} r={5} fill="rgba(217,119,87,0.55)" />
      <circle cx={260} cy={260} r={14} fill="none" stroke="rgba(217,119,87,0.4)" strokeWidth={1.5} />
    </svg>
  );
}

// ── Safe image with fallback ──────────────────────────────────────────────────

function SafeImg({
  src, alt, style, onError,
}: {
  src: string; alt: string;
  style?: React.CSSProperties;
  onError?: () => void;
}) {
  return (
    <img
      src={src} alt={alt}
      referrerPolicy="no-referrer"
      crossOrigin="anonymous"
      style={style}
      onError={onError}
    />
  );
}

// ── Star row ──────────────────────────────────────────────────────────────────

function Stars({ rating, size = 11 }: { rating: number; size?: number }) {
  const filled = Math.round(Math.min(Math.max(rating, 0), 10) / 2);
  return (
    <span style={{ display: "flex", gap: 1 }}>
      {Array.from({ length: 5 }, (_, i) => (
        <Star key={i} size={size}
          style={{ color: i < filled ? "#f59e0b" : "rgba(255,255,255,0.15)",
                   fill:  i < filled ? "#f59e0b" : "rgba(255,255,255,0.15)" }} />
      ))}
    </span>
  );
}

// ── Image strip (thumbnail row in the featured panel) ────────────────────────

function ImageStrip({
  images, activeIdx, onSelect,
}: {
  images: string[];
  activeIdx: number;
  onSelect: (i: number) => void;
}) {
  const [errors, setErrors] = useState<Set<number>>(new Set());
  const valid = images.filter((_, i) => !errors.has(i));
  if (valid.length <= 1) return null;

  return (
    <div style={{
      display: "flex", gap: 4, overflowX: "auto", paddingBottom: 2,
      scrollbarWidth: "none",
    }}>
      {images.map((src, i) => {
        if (errors.has(i)) return null;
        const isActive = i === activeIdx;
        return (
          <button key={i} onClick={e => { e.stopPropagation(); onSelect(i); }}
            style={{
              flexShrink: 0, width: 48, height: 36,
              borderRadius: 5, overflow: "hidden", cursor: "pointer",
              border: isActive ? "2px solid var(--sp-accent)" : "2px solid transparent",
              padding: 0, background: "#111",
              opacity: isActive ? 1 : 0.55,
              transition: "opacity 120ms, border 120ms",
            }}
          >
            <SafeImg src={src} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }}
              onError={() => setErrors(p => new Set(p).add(i))} />
          </button>
        );
      })}
    </div>
  );
}

// ── Full-screen image gallery (used in modal) ─────────────────────────────────

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
    <div style={{ position: "relative", height: 230, overflow: "hidden", background: "#0a0a0a" }}>
      <SafeImg src={images[idx]} alt={name}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
        onError={() => setErrors(p => new Set(p).add(idx))} />
      <div style={{
        position: "absolute", inset: 0,
        background: "linear-gradient(to top, rgba(0,0,0,0.75) 0%, transparent 55%)",
      }} />
      {valid.length > 1 && (
        <>
          <button onClick={e => { e.stopPropagation(); prev(); }} style={{
            position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)",
            background: "rgba(0,0,0,0.52)", border: 0, borderRadius: 99,
            padding: 6, cursor: "pointer", color: "#fff", display: "flex",
          }}>
            <ChevronLeft size={15} />
          </button>
          <button onClick={e => { e.stopPropagation(); next(); }} style={{
            position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
            background: "rgba(0,0,0,0.52)", border: 0, borderRadius: 99,
            padding: 6, cursor: "pointer", color: "#fff", display: "flex",
          }}>
            <ChevronRight size={15} />
          </button>
          {/* Dot indicators */}
          <div style={{
            position: "absolute", bottom: 8, left: "50%", transform: "translateX(-50%)",
            display: "flex", gap: 4,
          }}>
            {images.map((_, i) => !errors.has(i) && (
              <button key={i} onClick={e => { e.stopPropagation(); setIdx(i); }}
                style={{
                  width: 6, height: 6, borderRadius: 99, border: 0, cursor: "pointer",
                  background: i === idx ? "#fff" : "rgba(255,255,255,0.3)", padding: 0,
                }} />
            ))}
          </div>
          {/* Thumbnail strip inside gallery */}
          <div style={{
            position: "absolute", bottom: 24, left: 10, right: 10,
            display: "flex", gap: 4, overflowX: "auto", scrollbarWidth: "none",
          }}>
            {images.map((src, i) => !errors.has(i) && (
              <button key={i} onClick={e => { e.stopPropagation(); setIdx(i); }}
                style={{
                  flexShrink: 0, width: 44, height: 32,
                  borderRadius: 4, overflow: "hidden", cursor: "pointer", padding: 0,
                  border: i === idx ? "2px solid var(--sp-accent)" : "2px solid rgba(255,255,255,0.2)",
                  background: "#000", opacity: i === idx ? 1 : 0.6,
                  transition: "opacity 100ms",
                }}
              >
                <SafeImg src={src} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── Reviews section (used in modal) ──────────────────────────────────────────

function ReviewsSection({ reviews }: { reviews: Review[] }) {
  const [expanded, setExpanded] = useState(false);
  if (!reviews.length) return null;
  const shown = expanded ? reviews : reviews.slice(0, 3);

  return (
    <div>
      {/* Section header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <p className="sp-mono" style={{
          margin: 0, fontSize: 10, color: "var(--sp-ink-4)",
          textTransform: "uppercase", letterSpacing: "0.07em",
          display: "flex", alignItems: "center", gap: 5,
        }}>
          <MessageSquare size={11} /> Guest Reviews · {reviews.length}
        </p>
        {reviews.length > 3 && (
          <button onClick={() => setExpanded(v => !v)} style={{
            background: "none", border: 0, cursor: "pointer",
            fontSize: 11, color: "var(--sp-accent)", padding: 0,
          }}>
            {expanded ? "Show less" : `+${reviews.length - 3} more`}
          </button>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {shown.map((rev, i) => (
          <div key={i} style={{
            background: "rgba(255,255,255,0.03)",
            border: "1px solid var(--sp-line)",
            borderRadius: 8, padding: "10px 12px",
          }}>
            {/* Review meta */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              {rev.rating != null && (
                <span style={{
                  fontSize: 11, fontWeight: 600,
                  color: rev.rating >= 8 ? "#4caf7d" : rev.rating >= 6 ? "#f59e0b" : "var(--sp-err)",
                  background: rev.rating >= 8 ? "rgba(76,175,125,0.12)" : rev.rating >= 6 ? "rgba(245,158,11,0.12)" : "rgba(239,68,68,0.12)",
                  padding: "1px 6px", borderRadius: 4,
                }}>
                  {rev.rating.toFixed(1)}
                </span>
              )}
              {rev.author && (
                <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                  <User size={10} style={{ color: "var(--sp-ink-4)" }} />
                  <span style={{ fontSize: 11, color: "var(--sp-ink-3)", fontWeight: 500 }}>
                    {rev.author}
                  </span>
                </span>
              )}
              {rev.date && (
                <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", marginLeft: "auto" }}>
                  {rev.date}
                </span>
              )}
            </div>
            {/* Review text */}
            <p style={{
              margin: 0, fontSize: 12, color: "var(--sp-ink-3)",
              lineHeight: 1.6, fontStyle: "italic",
            }}>
              "{rev.text}"
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Detail modal ──────────────────────────────────────────────────────────────

function EntityDetailModal({ entity, onClose }: { entity: EntityCardData; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const price      = getPrice(entity);
  const externalUrl = getExternalUrl(entity);
  const mapsUrl    = getMapsUrl(entity);
  const tags       = entity.amenities || entity.features || [];
  const reviews    = entity.reviews || [];

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9500,
      background: "rgba(0,0,0,0.65)",
      display: "flex", alignItems: "center", justifyContent: "center",
      backdropFilter: "blur(6px)",
    }} onClick={onClose}>
      <div style={{
        width: "100%", maxWidth: 500,
        maxHeight: "90vh", overflowY: "auto",
        background: "var(--sp-bg-2)",
        border: "1px solid var(--sp-line-2)",
        borderRadius: 16,
        boxShadow: "0 24px 64px rgba(0,0,0,0.55)",
        position: "relative",
      }} onClick={e => e.stopPropagation()}>

        {/* Close button */}
        <button onClick={onClose} style={{
          position: "absolute", top: 12, right: 12, zIndex: 10,
          background: "rgba(0,0,0,0.45)", border: 0, borderRadius: 99,
          padding: 6, cursor: "pointer", color: "var(--sp-ink-3)", display: "flex",
        }}>
          <X size={15} />
        </button>

        {/* Image gallery */}
        {entity.images && entity.images.length > 0 && (
          <ImageGallery images={entity.images} name={entity.name} />
        )}

        <div style={{ padding: "18px 20px 22px", display: "flex", flexDirection: "column", gap: 14 }}>

          {/* Name + price */}
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

          {/* Rating */}
          {entity.rating != null && (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Stars rating={entity.rating} size={13} />
              <span style={{ fontSize: 14, fontWeight: 600, color: "var(--sp-ink)" }}>
                {entity.rating.toFixed(1)}
              </span>
              {entity.review_count != null && (
                <span style={{ fontSize: 12, color: "var(--sp-ink-4)" }}>
                  ({entity.review_count.toLocaleString()} reviews)
                </span>
              )}
            </div>
          )}

          {/* Status row */}
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
              {entity.hours && <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)" }}>{entity.hours}</span>}
              {entity.distance && <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)" }}>{entity.distance}</span>}
            </div>
          )}

          {/* Location */}
          {(entity.address || entity.location) && (
            <p style={{ margin: 0, display: "flex", alignItems: "flex-start", gap: 6, fontSize: 13, color: "var(--sp-ink-3)" }}>
              <MapPin size={14} style={{ color: "var(--sp-accent)", marginTop: 1, flexShrink: 0 }} />
              {entity.address || entity.location}
            </p>
          )}

          {/* Description / bio / plot */}
          {(entity.description || entity.bio || entity.plot) && (
            <p style={{ margin: 0, fontSize: 13, color: "var(--sp-ink-3)", lineHeight: 1.6 }}>
              {entity.description || entity.bio || entity.plot}
            </p>
          )}

          {/* Cuisine */}
          {entity.cuisine && (
            <p className="sp-mono" style={{ margin: 0, fontSize: 11, color: "var(--sp-ink-4)" }}>
              Cuisine: {entity.cuisine}
            </p>
          )}

          {/* ── Type-specific fields ───────────────────────────────────────── */}

          {/* Person */}
          {entity.title    && <DetailRow label="Occupation" value={entity.title} />}
          {entity.born     && <DetailRow label="Born" value={entity.born} />}
          {entity.nationality && <DetailRow label="Nationality" value={entity.nationality} />}
          {entity.known_for && <DetailRow label="Known for" value={entity.known_for} />}
          <TagList label="Social / Links" items={entity.social_links || []} />

          {/* Movie / Show */}
          {entity.year     && <DetailRow label="Year" value={entity.year} />}
          {entity.genre    && <DetailRow label="Genre" value={entity.genre} />}
          {entity.director && <DetailRow label="Director" value={entity.director} />}
          {entity.runtime  && <DetailRow label="Runtime" value={entity.runtime} />}
          <TagList label="Cast" items={entity.cast || []} />
          <TagList label="Streaming on" items={entity.streaming_on || []} />

          {/* Event */}
          {entity.date     && <DetailRow label="Date" value={entity.date} />}
          {entity.time     && <DetailRow label="Time" value={entity.time} />}
          {entity.venue    && <DetailRow label="Venue" value={entity.venue} />}
          {entity.category && !["hotel","restaurant","local_business"].includes(entity.type || "") &&
            <DetailRow label="Category" value={entity.category} />}

          {/* College */}
          {entity.ranking  && <DetailRow label="Ranking" value={entity.ranking} />}
          {entity.acceptance_rate && <DetailRow label="Acceptance" value={entity.acceptance_rate} />}
          <TagList label="Programs" items={entity.programs || []} />

          {/* Flight */}
          {entity.airline   && <DetailRow label="Airline" value={entity.airline} />}
          {entity.departure && <DetailRow label="Departure" value={entity.departure} />}
          {entity.arrival   && <DetailRow label="Arrival" value={entity.arrival} />}
          {entity.duration  && <DetailRow label="Duration" value={entity.duration} />}
          {entity.stops     && <DetailRow label="Stops" value={entity.stops} />}
          {entity.aircraft  && <DetailRow label="Aircraft" value={entity.aircraft} />}

          {/* ── End type-specific fields ───────────────────────────────────── */}

          {/* Feature tags */}
          {tags.length > 0 && (
            <div>
              <p className="sp-mono" style={{ margin: "0 0 7px", fontSize: 10, color: "var(--sp-ink-4)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
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

          {/* Reviews */}
          {reviews.length > 0 && (
            <div style={{ borderTop: "1px solid var(--sp-line)", paddingTop: 14 }}>
              <ReviewsSection reviews={reviews} />
            </div>
          )}

          {/* Action buttons */}
          <div style={{ display: "flex", gap: 8, paddingTop: 4, borderTop: "1px solid var(--sp-line)" }}>
            {mapsUrl && (
              <a href={mapsUrl} target="_blank" rel="noreferrer" style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "8px 14px", borderRadius: 7,
                background: "var(--sp-accent)", color: "#1a1208",
                fontSize: 12, fontWeight: 600, textDecoration: "none",
              }}>
                <Navigation size={12} /> Get directions
              </a>
            )}
            {entity.phone && (
              <a href={`tel:${entity.phone}`} style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "8px 13px", borderRadius: 7,
                background: "var(--sp-bg-3)", border: "1px solid var(--sp-line-2)",
                color: "var(--sp-ink-2)", fontSize: 12, textDecoration: "none",
              }}>
                <Phone size={12} /> Call
              </a>
            )}
            {externalUrl && (
              <a href={externalUrl} target="_blank" rel="noreferrer" style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "8px 13px", borderRadius: 7,
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

// ── Live action panel (Buy/Book/Play progress) ──────────────────────────────
//
// Renders BELOW the entity card once the user clicks an action button.
// Mirrors what the post-payment receipt watcher is doing in real time —
// adapter stage transitions, "waiting for payment" reminders, capture,
// cancellation. Keeping it below (not inside) the card means the rich
// product visual stays clean while a checkout is in flight.

function ActionProgressPanel({
  progress, entityName,
}: {
  progress: EntityActionProgress;
  entityName: string;
}) {
  const isDone = progress.status === "completed";
  const isFail = progress.status === "failed";
  const isRunning = !isDone && !isFail;
  const message = (
    (isDone || isFail) ? (progress.result_summary || progress.latest_step) : progress.latest_step
  ) || (isRunning ? "Working…" : "Done");

  const tint = isFail ? "rgba(220, 80, 80, 0.55)"
             : isDone ? "rgba(80, 180, 120, 0.55)"
             : "var(--sp-accent)";
  const bg   = isFail ? "rgba(220, 80, 80, 0.06)"
             : isDone ? "rgba(80, 180, 120, 0.06)"
             : "rgba(217, 119, 87, 0.06)";
  const statusLabel = isFail ? "stopped" : isDone ? "done" : "running";

  return (
    <div style={{
      marginTop: 8,
      borderRadius: 10,
      border: `1px solid ${tint}`,
      background: bg,
      padding: "10px 14px",
      display: "flex", flexDirection: "column", gap: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{
          width: 8, height: 8, borderRadius: "50%",
          background: tint,
          boxShadow: isRunning ? `0 0 8px ${tint}` : "none",
          animation: isRunning ? "sp-pulse 1.2s ease-in-out infinite" : "none",
          flexShrink: 0,
        }} />
        <span className="sp-mono" style={{
          fontSize: 10, color: "var(--sp-ink-4)",
          textTransform: "uppercase", letterSpacing: "0.08em",
        }}>
          Browser action · {statusLabel}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontSize: 11, color: "var(--sp-ink-3)",
          maxWidth: "60%",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {entityName}
        </span>
      </div>
      <p style={{
        margin: 0, fontSize: 13, color: "var(--sp-ink-2)", lineHeight: 1.4,
      }}>
        {message}
      </p>
    </div>
  );
}


// ── Featured panel (left 55%) ─────────────────────────────────────────────────

function FeaturedPanel({
  entity, rank, onOpenDetail, onAction,
}: {
  entity: EntityCardData;
  rank: number;
  onOpenDetail: () => void;
  onAction?: (action: string, entity: EntityCardData) => void;
}) {
  const images   = entity.images || [];
  const [bgIdx, setBgIdx]   = useState(0);
  const [imgErrors, setImgErrors] = useState<Set<number>>(new Set());

  // Reset to the first image when the entity changes (adjusting state during render).
  const [shownEntity, setShownEntity] = useState(entity.name);
  if (shownEntity !== entity.name) {
    setShownEntity(entity.name);
    setBgIdx(0);
    setImgErrors(new Set());
  }

  const bgSrc  = images[bgIdx] && !imgErrors.has(bgIdx) ? images[bgIdx] : null;
  const hasImg = !!bgSrc;

  const price      = getPrice(entity);
  const tags       = entity.amenities || entity.features || [];
  const externalUrl = getExternalUrl(entity);
  const mapsUrl    = getMapsUrl(entity);
  const firstReview = entity.reviews?.[0];

  return (
    <div onClick={onOpenDetail} style={{
      flex: "0 0 55%",
      position: "relative", overflow: "hidden",
      padding: "16px 14px 14px",
      borderRight: "1px solid var(--sp-line)",
      display: "flex", flexDirection: "column", gap: 9,
      minHeight: 300, cursor: "pointer",
      background: "var(--sp-bg)",
    }}>
      {/* Background image */}
      {hasImg ? (
        <>
          <SafeImg src={bgSrc!} alt={entity.name}
            onError={() => setImgErrors(p => new Set(p).add(bgIdx))}
            style={{
              position: "absolute", inset: 0,
              width: "100%", height: "100%",
              objectFit: "cover", opacity: 0.32,
            }} />
          <div style={{
            position: "absolute", inset: 0,
            background: "linear-gradient(135deg, var(--sp-bg) 10%, rgba(0,0,0,0.3) 100%)",
          }} />
        </>
      ) : (
        <RadialBg />
      )}

      {/* Content */}
      <div style={{ position: "relative", zIndex: 1, display: "flex", flexDirection: "column", gap: 8, flex: 1 }}>

        {/* Rank + type chips */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{
            fontSize: 10, fontWeight: 700, color: "#1a1208",
            background: "var(--sp-accent)", padding: "2px 7px", borderRadius: 4,
          }}>
            #{rank}
          </span>
          {(entity.type_label || entity.type) && (
            <span className="sp-mono" style={{
              fontSize: 10, color: "var(--sp-ink-4)",
              background: "rgba(255,255,255,0.05)",
              border: "1px solid var(--sp-line)", padding: "2px 7px", borderRadius: 4,
            }}>
              {entity.type_label || entity.type}
            </span>
          )}
          {entity.brand && (
            <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-accent)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              {entity.brand}
            </span>
          )}
        </div>

        {/* Name */}
        <h3 style={{
          margin: 0, fontSize: 18, fontWeight: 700,
          color: "var(--sp-ink)", lineHeight: 1.2, letterSpacing: "-0.02em",
        }}>
          {entity.name}
        </h3>

        {/* Rating · price · open */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {entity.rating != null && (
            <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <Stars rating={entity.rating} size={11} />
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
          {price && (
            <span style={{
              fontSize: 11, fontWeight: 600, color: "#4caf7d",
              background: "rgba(76,175,125,0.12)",
              padding: "1px 7px", borderRadius: 4,
            }}>
              {price}
            </span>
          )}
          {entity.open_now != null && (
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <span style={{
                width: 5, height: 5, borderRadius: 99,
                background: entity.open_now ? "var(--sp-ok)" : "var(--sp-err)",
              }} />
              <span className="sp-mono" style={{ fontSize: 11, color: entity.open_now ? "var(--sp-ok)" : "var(--sp-err)" }}>
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
        </div>

        {/* Location */}
        {(entity.address || entity.location) && (
          <div style={{ display: "flex", alignItems: "flex-start", gap: 5 }}>
            <MapPin size={11} style={{ color: "var(--sp-accent)", marginTop: 1, flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: "var(--sp-ink-3)", lineHeight: 1.35 }}>
              {entity.address || entity.location}
            </span>
          </div>
        )}

        {/* Cuisine */}
        {entity.cuisine && (
          <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>
            {entity.cuisine}
          </span>
        )}

        {/* Feature tags */}
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

        {/* First review snippet */}
        {firstReview && (
          <div style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid var(--sp-line)",
            borderRadius: 7, padding: "7px 10px",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
              <MessageSquare size={9} style={{ color: "var(--sp-ink-4)" }} />
              {firstReview.rating != null && (
                <span style={{
                  fontSize: 10, fontWeight: 600,
                  color: firstReview.rating >= 8 ? "#4caf7d" : firstReview.rating >= 6 ? "#f59e0b" : "var(--sp-err)",
                }}>
                  {firstReview.rating.toFixed(1)}
                </span>
              )}
              {firstReview.author && (
                <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)" }}>
                  {firstReview.author}
                </span>
              )}
            </div>
            <p style={{ margin: 0, fontSize: 11, color: "var(--sp-ink-3)", lineHeight: 1.5, fontStyle: "italic" }}>
              "{firstReview.text.length > 90 ? firstReview.text.slice(0, 90) + "…" : firstReview.text}"
            </p>
          </div>
        )}

        {/* Image strip */}
        {images.length > 1 && (
          <div onClick={e => e.stopPropagation()}>
            <ImageStrip images={images} activeIdx={bgIdx} onSelect={setBgIdx} />
          </div>
        )}

        {/* Action buttons */}
        <div style={{ marginTop: "auto", display: "flex", alignItems: "center", gap: 6 }}
          onClick={e => e.stopPropagation()}>
          {/* Entity-specific primary action */}
          {onAction && (() => {
            const act = getEntityAction(entity);
            if (!act) return null;
            return (
              <button
                onClick={e => { e.stopPropagation(); onAction(act.actionKey, entity); }}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 5,
                  padding: "6px 11px", borderRadius: 7,
                  background: "var(--sp-accent)", color: "#1a1208",
                  fontSize: 11, fontWeight: 700, border: "none", cursor: "pointer",
                }}
              >
                <act.Icon size={11} /> {act.label}
              </button>
            );
          })()}
          {mapsUrl && (
            <a href={mapsUrl} target="_blank" rel="noreferrer" style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              padding: "6px 11px", borderRadius: 7,
              background: onAction && getEntityAction(entity) ? "var(--sp-bg-3)" : "var(--sp-accent)",
              color: onAction && getEntityAction(entity) ? "var(--sp-ink-2)" : "#1a1208",
              border: onAction && getEntityAction(entity) ? "1px solid var(--sp-line-2)" : "none",
              fontSize: 11, fontWeight: 600, textDecoration: "none",
            }}>
              <Navigation size={11} /> Directions
            </a>
          )}
          {entity.phone && (
            <a href={`tel:${entity.phone}`} style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              padding: "6px 10px", borderRadius: 7,
              background: "var(--sp-bg-3)", border: "1px solid var(--sp-line-2)",
              color: "var(--sp-ink-2)", fontSize: 11, textDecoration: "none",
            }}>
              <Phone size={11} /> Call
            </a>
          )}
          {externalUrl && (
            <a href={externalUrl} target="_blank" rel="noreferrer" style={{
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              width: 30, height: 30, borderRadius: 7,
              background: "var(--sp-bg-3)", border: "1px solid var(--sp-line)",
              color: "var(--sp-ink-4)", textDecoration: "none",
            }}>
              <ExternalLink size={11} />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Entity list row (own component so hooks are legal) ────────────────────────

function EntityRow({
  entity, index, isActive, isLast, onSelect,
}: {
  entity: EntityCardData;
  index: number;
  isActive: boolean;
  isLast: boolean;
  onSelect: () => void;
}) {
  const [thumbErr, setThumbErr] = useState(false);
  const thumb = entity.images?.[0];
  const price = getPrice(entity);

  return (
    <div onClick={onSelect} style={{
      display: "flex", alignItems: "flex-start", gap: 9,
      padding: "10px 12px",
      borderBottom: !isLast ? "1px solid var(--sp-line)" : "none",
      background: isActive ? "rgba(217,119,87,0.07)" : "transparent",
      cursor: "pointer", transition: "background 120ms",
    }}
      onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLDivElement).style.background = "rgba(255,255,255,0.02)"; }}
      onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
    >
      {/* Rank */}
      <span style={{
        fontSize: 13, fontWeight: 700,
        color: isActive ? "var(--sp-accent)" : "var(--sp-ink-4)",
        minWidth: 16, flexShrink: 0, paddingTop: 2,
      }}>
        {index + 1}
      </span>

      {/* Thumbnail */}
      {thumb && !thumbErr ? (
        <div style={{ width: 42, height: 36, borderRadius: 5, overflow: "hidden", flexShrink: 0, background: "#111" }}>
          <SafeImg src={thumb} alt={entity.name}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
            onError={() => setThumbErr(true)} />
        </div>
      ) : (
        <div style={{
          width: 42, height: 36, borderRadius: 5, flexShrink: 0,
          background: "rgba(217,119,87,0.08)", border: "1px solid var(--sp-line)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <MapPin size={12} style={{ color: "var(--sp-accent)", opacity: 0.5 }} />
        </div>
      )}

      {/* Info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{
          margin: 0, fontSize: 12, fontWeight: 500, lineHeight: 1.3,
          color: isActive ? "var(--sp-ink)" : "var(--sp-ink-2)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
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
          {price && (
            <span className="sp-mono" style={{ fontSize: 10, color: "#4caf7d" }}>{price}</span>
          )}
          {entity.reviews && entity.reviews.length > 0 && (
            <span style={{ display: "flex", alignItems: "center", gap: 2 }}>
              <MessageSquare size={8} style={{ color: "var(--sp-ink-4)" }} />
              <span className="sp-mono" style={{ fontSize: 9, color: "var(--sp-ink-4)" }}>
                {entity.reviews.length} reviews
              </span>
            </span>
          )}
          {entity.open_now != null && (
            <span style={{ display: "flex", alignItems: "center", gap: 2 }}>
              <span style={{ width: 4, height: 4, borderRadius: 99, background: entity.open_now ? "var(--sp-ok)" : "var(--sp-err)" }} />
              <span className="sp-mono" style={{ fontSize: 10, color: entity.open_now ? "var(--sp-ok)" : "var(--sp-err)" }}>
                {entity.open_now ? "Open" : "Closed"}
              </span>
            </span>
          )}
        </div>
      </div>

      {entity.distance && (
        <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", flexShrink: 0, paddingTop: 2 }}>
          {entity.distance}
        </span>
      )}
    </div>
  );
}

// ── Entity list (right panel) ─────────────────────────────────────────────────

function EntityList({
  entities, activeIdx, onSelect,
}: {
  entities: EntityCardData[];
  activeIdx: number;
  onSelect: (i: number) => void;
}) {
  return (
    <div style={{ flex: 1, overflowY: "auto", maxHeight: 360, background: "var(--sp-bg-2)" }}>
      {entities.map((entity, i) => (
        <EntityRow
          key={i}
          entity={entity}
          index={i}
          isActive={i === activeIdx}
          isLast={i === entities.length - 1}
          onSelect={() => onSelect(i)}
        />
      ))}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function EntityCards({ entities, intent, onDismiss, onAction, entityActions }: EntityCardsProps) {
  const [featuredIdx, setFeaturedIdx] = useState(0);
  const [showModal, setShowModal]     = useState(false);

  if (!entities?.length) return null;

  const featured = entities[featuredIdx];
  // Match by normalised name — matches the server-side entity_key in
  // chat_utils.entity_card_action (title.lower()).
  const actionFor = (e?: EntityCardData): EntityActionProgress | undefined => {
    if (!e || !entityActions?.length) return undefined;
    const key = (e.name || "").trim().toLowerCase();
    if (!key) return undefined;
    return entityActions.find(a => a.entity_key === key);
  };
  const label = intent
    ? intent.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())
    : "Results";

  const nearCity = entities[0]?.location?.split(",")[0]?.trim()
    || entities[0]?.address?.split(",").slice(-2, -1)[0]?.trim();

  const totalReviews = entities.reduce((n, e) => n + (e.reviews?.length || 0), 0);

  const mapsSearchUrl = nearCity || featured?.name
    ? `https://www.google.com/maps/search/${encodeURIComponent(`${label} ${nearCity || ""}`.trim())}`
    : null;

  return (
    <>
      <div style={{
        borderRadius: 12, border: "1px solid var(--sp-line)",
        overflow: "hidden", background: "var(--sp-bg-2)",
      }}>
        {/* Header */}
        <div style={{
          padding: "10px 14px",
          display: "flex", alignItems: "center", gap: 8,
          borderBottom: "1px solid var(--sp-line)",
        }}>
          <MapPin size={13} style={{ color: "var(--sp-accent)", flexShrink: 0 }} />
          <span style={{ fontSize: 12, fontWeight: 500, color: "var(--sp-ink)" }}>{label}</span>
          <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>
            · {entities.length} found{nearCity ? ` in ${nearCity}` : ""}
          </span>
          {totalReviews > 0 && (
            <span className="sp-mono" style={{
              fontSize: 10, color: "var(--sp-ink-4)",
              background: "rgba(255,255,255,0.04)",
              border: "1px solid var(--sp-line)",
              padding: "1px 6px", borderRadius: 4,
              display: "flex", alignItems: "center", gap: 3,
            }}>
              <MessageSquare size={9} /> {totalReviews} reviews
            </span>
          )}
          <div style={{ flex: 1 }} />
          {mapsSearchUrl && (
            <a href={mapsSearchUrl} target="_blank" rel="noreferrer" style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 11, color: "var(--sp-ink-3)",
              background: "var(--sp-bg-3)", border: "1px solid var(--sp-line)",
              padding: "3px 9px", borderRadius: 5, textDecoration: "none",
            }}>
              Map
            </a>
          )}
          <button onClick={onDismiss} style={{
            background: "transparent", border: 0, cursor: "pointer",
            color: "var(--sp-ink-4)", display: "flex", padding: 2,
          }}>
            <X size={13} />
          </button>
        </div>

        {/* Split body */}
        <div style={{ display: "flex" }}>
          <FeaturedPanel
            entity={featured}
            rank={featuredIdx + 1}
            onOpenDetail={() => setShowModal(true)}
            onAction={onAction}
          />
          <EntityList
            entities={entities}
            activeIdx={featuredIdx}
            onSelect={i => { setFeaturedIdx(i); setShowModal(false); }}
          />
        </div>
      </div>

      {/* Live action progress for the featured entity. Rendered as a
          sibling of the card (not inside the FeaturedPanel) so the
          checkout-watcher's stage transitions get real estate of their
          own and don't squeeze the product image. */}
      {(() => {
        const p = actionFor(featured);
        if (!p) return null;
        return <ActionProgressPanel progress={p} entityName={featured.name} />;
      })()}

      {showModal && (
        <EntityDetailModal entity={featured} onClose={() => setShowModal(false)} />
      )}
    </>
  );
}
