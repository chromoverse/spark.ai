import React, { useState, useEffect, useCallback } from "react";
import { X, Star, MapPin, ExternalLink, DollarSign, ChevronLeft, ChevronRight, ChevronDown, ChevronUp } from "lucide-react";

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
}

interface EntityCardsProps {
  entities: EntityCardData[];
  intent?: string;
  onDismiss: () => void;
}

/* ─── Shared sub-components ────────────────────────────────────────────── */

function StarRating({ rating, size = "sm" }: { rating: number; size?: "sm" | "md" }) {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;
  const iconSize = size === "md" ? 14 : 12;
  return (
    <span className="flex items-center gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <Star
          key={i}
          size={iconSize}
          className={
            i < full
              ? "fill-amber-400 text-amber-400"
              : i === full && half
                ? "fill-amber-400/50 text-amber-400"
                : "fill-neutral-700 text-neutral-700"
          }
        />
      ))}
      <span className={`ml-1 text-neutral-400 ${size === "md" ? "text-sm" : "text-xs"}`}>
        {rating.toFixed(1)}
      </span>
    </span>
  );
}

function PriceTag({ entity, size = "sm" }: { entity: EntityCardData; size?: "sm" | "md" }) {
  const price = entity.price_per_night || entity.price || entity.price_range;
  if (!price) return null;
  return (
    <span className={`flex items-center gap-1 rounded-full bg-emerald-900/40 font-semibold text-emerald-400 ${
      size === "md" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-xs"
    }`}>
      <DollarSign size={size === "md" ? 12 : 10} />
      {price}
    </span>
  );
}

function ActionLink({ url, label, primary = false }: { url: string; label: string; primary?: boolean }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      onClick={(e) => e.stopPropagation()}
      className={`flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
        primary
          ? "bg-indigo-600 text-white hover:bg-indigo-500"
          : "bg-neutral-800 text-neutral-300 hover:bg-neutral-700"
      }`}
    >
      {label} <ExternalLink size={10} />
    </a>
  );
}

function MapLink({ entity, compact = false }: { entity: EntityCardData; compact?: boolean }) {
  const url =
    entity.maps_url
    || (entity.address ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${entity.name}, ${entity.address}`)}` : "")
    || (entity.location ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${entity.name}, ${entity.location}`)}` : "");
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      onClick={(e) => e.stopPropagation()}
      title="Open in Google Maps"
      className={
        compact
          ? "flex items-center gap-1 rounded-full bg-rose-900/40 px-2 py-0.5 text-xs font-medium text-rose-300 hover:bg-rose-900/70 transition-colors"
          : "flex items-center gap-1 rounded-full bg-rose-900/40 px-2.5 py-1 text-xs font-medium text-rose-300 hover:bg-rose-900/70 transition-colors"
      }
    >
      <MapPin size={compact ? 10 : 11} />
      {compact ? "Map" : "View on Map"}
    </a>
  );
}

/* ─── Detail Modal ─────────────────────────────────────────────────────── */

function ImageGallery({ images, name }: { images: string[]; name: string }) {
  const [idx, setIdx] = useState(0);
  const [errors, setErrors] = useState<Set<number>>(new Set());

  const validImages = images.filter((_, i) => !errors.has(i));
  const currentSrc = images[idx];
  const hasMultiple = validImages.length > 1;

  const prev = useCallback(() => {
    let next = idx - 1;
    while (next >= 0 && errors.has(next)) next--;
    if (next >= 0) setIdx(next);
  }, [idx, errors]);

  const next = useCallback(() => {
    let n = idx + 1;
    while (n < images.length && errors.has(n)) n++;
    if (n < images.length) setIdx(n);
  }, [idx, images.length, errors]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") prev();
      if (e.key === "ArrowRight") next();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [prev, next]);

  if (!currentSrc || errors.has(idx)) return null;

  return (
    <div className="relative h-56 w-full overflow-hidden rounded-xl bg-neutral-900">
      <img
        src={currentSrc}
        alt={name}
        referrerPolicy="no-referrer"
        className="h-full w-full object-cover"
        onError={() => setErrors(prev => new Set(prev).add(idx))}
      />
      <div className="absolute inset-0 bg-gradient-to-t from-neutral-950/80 via-transparent to-transparent" />

      {hasMultiple && (
        <>
          <button
            onClick={(e) => { e.stopPropagation(); prev(); }}
            className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-1.5 text-white hover:bg-black/80 transition-colors"
          >
            <ChevronLeft size={16} />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); next(); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-1.5 text-white hover:bg-black/80 transition-colors"
          >
            <ChevronRight size={16} />
          </button>
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-1.5">
            {images.map((_, i) =>
              !errors.has(i) && (
                <button
                  key={i}
                  onClick={(e) => { e.stopPropagation(); setIdx(i); }}
                  className={`w-2 h-2 rounded-full transition-colors ${
                    i === idx ? "bg-white" : "bg-white/30 hover:bg-white/60"
                  }`}
                />
              )
            )}
          </div>
        </>
      )}
    </div>
  );
}

function EntityDetailModal({ entity, onClose }: { entity: EntityCardData; onClose: () => void }) {
  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const bookingUrl = entity.booking_url || entity.buy_url || entity.menu_url || entity.website;
  const amenities = entity.amenities || entity.features || [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl border border-neutral-700/50 bg-neutral-950 shadow-2xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute right-3 top-3 z-10 rounded-full bg-black/50 p-1.5 text-neutral-400 hover:text-white hover:bg-black/80 transition-colors"
        >
          <X size={16} />
        </button>

        {/* Images */}
        {entity.images && entity.images.length > 0 && (
          <ImageGallery images={entity.images} name={entity.name} />
        )}

        {/* Content */}
        <div className="p-5 space-y-4">
          {/* Title + price */}
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-white leading-tight">{entity.name}</h2>
              {entity.brand && (
                <p className="text-xs font-medium uppercase tracking-wide text-indigo-400 mt-0.5">{entity.brand}</p>
              )}
            </div>
            <PriceTag entity={entity} size="md" />
          </div>

          {/* Rating */}
          {entity.rating != null && (
            <div className="flex items-center gap-2">
              <StarRating rating={entity.rating} size="md" />
              {entity.review_count != null && (
                <span className="text-sm text-neutral-500">
                  ({entity.review_count.toLocaleString()} reviews)
                </span>
              )}
            </div>
          )}

          {/* Location */}
          {(entity.location || entity.address) && (
            <p className="flex items-center gap-1.5 text-sm text-neutral-400">
              <MapPin size={14} className="text-rose-400 shrink-0" />
              {entity.address || entity.location}
            </p>
          )}

          {/* Description */}
          {entity.description && (
            <p className="text-sm text-neutral-400 leading-relaxed">{entity.description}</p>
          )}

          {/* Cuisine */}
          {entity.cuisine && (
            <p className="text-sm text-neutral-500">Cuisine: {entity.cuisine}</p>
          )}

          {/* Amenities */}
          {amenities.length > 0 && (
            <div>
              <p className="text-xs font-medium text-neutral-500 uppercase tracking-wide mb-2">Amenities</p>
              <div className="flex flex-wrap gap-1.5">
                {amenities.map((a, i) => (
                  <span key={i} className="rounded-full bg-neutral-800 px-2.5 py-1 text-xs text-neutral-300">
                    {a}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-2 border-t border-neutral-800">
            {bookingUrl && <ActionLink url={bookingUrl} label="View Details" primary />}
            <MapLink entity={entity} />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── Cards ────────────────────────────────────────────────────────────── */

function FeaturedCard({ entity, onClick }: { entity: EntityCardData; onClick: () => void }) {
  const [imgError, setImgError] = useState(false);
  const img = entity.images?.[0];
  const hasImg = img && !imgError;

  return (
    <div
      className="relative overflow-hidden rounded-xl border border-indigo-500/30 bg-neutral-900 shadow-lg shadow-indigo-950/30 cursor-pointer hover:border-indigo-500/50 transition-colors"
      onClick={onClick}
    >
      {hasImg ? (
        <div className="relative h-44 w-full overflow-hidden">
          <img
            src={img}
            alt={entity.name}
            onError={() => setImgError(true)}
            referrerPolicy="no-referrer"
            loading="lazy"
            className="h-full w-full object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-neutral-900 via-neutral-900/20 to-transparent" />
          <div className="absolute bottom-0 left-0 p-3">
            <PriceTag entity={entity} />
          </div>
          <div className="absolute right-2 top-2 rounded-full bg-indigo-600 px-2 py-0.5 text-xs font-bold text-white">#1</div>
        </div>
      ) : (
        <div className="flex h-20 items-center justify-between bg-indigo-950/30 px-4">
          <span className="rounded-full bg-indigo-600 px-2 py-0.5 text-xs font-bold text-white">#1 Top Pick</span>
          <PriceTag entity={entity} />
        </div>
      )}

      <div className="p-4">
        <div className="mb-1 flex items-start justify-between gap-2">
          <h3 className="text-sm font-semibold leading-tight text-neutral-100">{entity.name}</h3>
          <div className="flex items-center gap-1.5">
            <MapLink entity={entity} compact />
          </div>
        </div>
        {entity.brand && <p className="mb-1 text-xs font-medium uppercase tracking-wide text-indigo-400">{entity.brand}</p>}
        {entity.rating != null && (
          <div className="mb-2">
            <StarRating rating={entity.rating} />
            {entity.review_count != null && <span className="ml-1 text-xs text-neutral-500">({entity.review_count.toLocaleString()})</span>}
          </div>
        )}
        {(entity.location || entity.address) && (
          <p className="mb-2 flex items-center gap-1 text-xs text-neutral-400">
            <MapPin size={11} />
            {entity.location || entity.address}
          </p>
        )}
        {(entity.amenities?.length || entity.features?.length) ? (
          <div className="flex flex-wrap gap-1">
            {(entity.amenities || entity.features || []).slice(0, 4).map((a, i) => (
              <span key={i} className="rounded-full bg-neutral-800 px-2 py-0.5 text-xs text-neutral-400">{a}</span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function SmallCard({ entity, rank, onClick }: { entity: EntityCardData; rank: number; onClick: () => void }) {
  const [hovered, setHovered] = useState(false);
  const [imgError, setImgError] = useState(false);
  const img = entity.images?.[0];
  const hasImg = img && !imgError;

  return (
    <div
      className="relative overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900/80 transition-all duration-200 hover:border-indigo-500/40 hover:bg-neutral-900 cursor-pointer"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
    >
      {hasImg && hovered && (
        <div className="absolute inset-0 z-10">
          <img
            src={img}
            alt={entity.name}
            onError={() => setImgError(true)}
            referrerPolicy="no-referrer"
            loading="lazy"
            className="h-full w-full object-cover opacity-20"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-neutral-900 via-neutral-900/60 to-neutral-900/40" />
        </div>
      )}

      <div className="relative z-20 p-3">
        <div className="mb-1 flex items-start justify-between gap-1">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-neutral-600">#{rank}</span>
            <h4 className="line-clamp-1 text-xs font-medium text-neutral-200">{entity.name}</h4>
          </div>
          <MapLink entity={entity} compact />
        </div>
        {entity.brand && <p className="mb-1 line-clamp-1 text-xs uppercase tracking-wide text-indigo-400">{entity.brand}</p>}
        <div className="flex flex-wrap items-center gap-2">
          {entity.rating != null && <StarRating rating={entity.rating} />}
          <PriceTag entity={entity} />
        </div>
        {(entity.location || entity.address) && (
          <p className="mt-1 flex items-center gap-1 text-xs text-neutral-500">
            <MapPin size={10} />
            <span className="line-clamp-1">{entity.location || entity.address}</span>
          </p>
        )}
        {entity.cuisine && <p className="mt-1 text-xs text-neutral-500">{entity.cuisine}</p>}
      </div>
    </div>
  );
}

/* ─── Main Component ───────────────────────────────────────────────────── */

const INITIAL_VISIBLE = 8;

export default function EntityCards({ entities, intent, onDismiss }: EntityCardsProps) {
  const [showAll, setShowAll] = useState(false);
  const [selectedEntity, setSelectedEntity] = useState<EntityCardData | null>(null);

  if (!entities || entities.length === 0) return null;

  const [featured, ...rest] = entities;
  const visible = showAll ? rest : rest.slice(0, INITIAL_VISIBLE);
  const hasMore = rest.length > INITIAL_VISIBLE;

  const label = intent
    ? intent.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
    : "Results";

  return (
    <>
      <div className="rounded-xl border border-neutral-800 bg-neutral-950 p-4">
        {/* Header */}
        <div className="mb-3 flex items-center justify-between">
          <div>
            <span className="text-sm font-semibold text-neutral-200">{label}</span>
            <span className="ml-2 text-xs text-neutral-500">{entities.length} found</span>
          </div>
          <button
            onClick={onDismiss}
            className="rounded-md p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-300 transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* Featured top card */}
        <div className="mb-3">
          <FeaturedCard entity={featured} onClick={() => setSelectedEntity(featured)} />
        </div>

        {/* Grid of cards */}
        {visible.length > 0 && (
          <div className="grid grid-cols-2 gap-2">
            {visible.map((entity, i) => (
              <SmallCard
                key={i}
                entity={entity}
                rank={i + 2}
                onClick={() => setSelectedEntity(entity)}
              />
            ))}
          </div>
        )}

        {/* Show more / less */}
        {hasMore && (
          <button
            onClick={() => setShowAll((v) => !v)}
            className="mt-2 w-full flex items-center justify-center gap-1 rounded-lg bg-neutral-900 py-1.5 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-neutral-300 transition-colors"
          >
            {showAll ? (
              <><ChevronUp size={12} /> Show less</>
            ) : (
              <><ChevronDown size={12} /> Show all {entities.length} results</>
            )}
          </button>
        )}
      </div>

      {/* Detail modal */}
      {selectedEntity && (
        <EntityDetailModal
          entity={selectedEntity}
          onClose={() => setSelectedEntity(null)}
        />
      )}
    </>
  );
}
