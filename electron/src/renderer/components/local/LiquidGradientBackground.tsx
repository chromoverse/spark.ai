import { useEffect, useRef, useCallback } from "react";

// ─── Constants ────────────────────────────────────────────────────────────────
// ─── Spring physics config ─────────────────────────────────────────────────────
const SPRING_STIFFNESS = 0.11;
const SPRING_DAMPING = 0.68;
const VELOCITY_ROT = 24;

// ─── Component ────────────────────────────────────────────────────────────────
export default function LiquidGradientBackground() {
  const glowRef = useRef<HTMLDivElement>(null);
  const slowLayerRef = useRef<HTMLDivElement>(null);
  const midLayerRef = useRef<HTMLDivElement>(null);
  const fastLayerRef = useRef<HTMLDivElement>(null);

  const rafRef = useRef<number | null>(null);

  const txRef = useRef(0.5);
  const tyRef = useRef(0.5);
  const cxRef = useRef(0.5);
  const cyRef = useRef(0.5);
  const vxRef = useRef(0);
  const vyRef = useRef(0);

  // ── Spring-physics parallax loop ─────────────────────────────────────────
  const animate = useCallback(() => {
    const ax = (txRef.current - cxRef.current) * SPRING_STIFFNESS;
    const ay = (tyRef.current - cyRef.current) * SPRING_STIFFNESS;

    vxRef.current = vxRef.current * SPRING_DAMPING + ax;
    vyRef.current = vyRef.current * SPRING_DAMPING + ay;

    cxRef.current += vxRef.current;
    cyRef.current += vyRef.current;

    const dx = cxRef.current - 0.5;
    const dy = cyRef.current - 0.5;

    const tiltX = vyRef.current * VELOCITY_ROT;
    const tiltY = -vxRef.current * VELOCITY_ROT;

    if (slowLayerRef.current) {
      slowLayerRef.current.style.transform = `translate(${dx * 30}px, ${dy * 22}px) rotate(${tiltX * 0.4}deg)`;
    }
    if (midLayerRef.current) {
      midLayerRef.current.style.transform = `translate(${dx * 55}px, ${dy * 40}px) rotate(${tiltY * 0.6}deg)`;
    }
    if (fastLayerRef.current) {
      fastLayerRef.current.style.transform = `translate(${dx * 85}px, ${dy * 62}px) rotate(${tiltX * 0.9}deg)`;
    }

    const settling =
      Math.abs(vxRef.current) < 0.0002 &&
      Math.abs(vyRef.current) < 0.0002 &&
      Math.abs(txRef.current - cxRef.current) < 0.0003 &&
      Math.abs(tyRef.current - cyRef.current) < 0.0003;

    if (settling) {
      rafRef.current = null;
      return;
    }
    rafRef.current = requestAnimationFrame(animate);
  }, []);

  // ── Event listeners ───────────────────────────────────────────────────────
  useEffect(() => {
    const onPointerMove = (e: PointerEvent) => {
      txRef.current = e.clientX / window.innerWidth;
      tyRef.current = e.clientY / window.innerHeight;
      if (glowRef.current) {
        glowRef.current.style.left = `${e.clientX}px`;
        glowRef.current.style.top = `${e.clientY}px`;
      }
      if (!rafRef.current) rafRef.current = requestAnimationFrame(animate);
    };

    const onPointerLeave = () => {
      txRef.current = 0.5;
      tyRef.current = 0.5;
      if (!rafRef.current) rafRef.current = requestAnimationFrame(animate);
    };

    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerleave", onPointerLeave);

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerleave", onPointerLeave);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [animate]);

  // ──────────────────────────────────────────────────────────────────────────
  return (
    <>
      <style>{`
        .gradient-bg {
          position: fixed;
          inset: 0;
          overflow: hidden;
          isolation: isolate;
          background: radial-gradient(ellipse 130% 90% at 50% 115%, #0e0820 0%, #080612 50%, #070810 100%);
        }

        /* ═══════════════════════════════════════════════════════════════════
           LAYER 1 — Base glow  (z-index 1, blur 180px)
        ═══════════════════════════════════════════════════════════════════ */
        .layer-base {
          position: absolute;
          inset: -40%;
          z-index: 1;
          will-change: transform;
          animation: baseFloat 30s ease-in-out infinite;
          filter: blur(180px);
          opacity: 0.52;
          mix-blend-mode: screen;
        }
        .base-blob-a {
          position: absolute;
          width: 70%; height: 65%;
          top: 15%; left: -5%;
          border-radius: 62% 38% 55% 45% / 48% 60% 40% 52%;
          background: radial-gradient(ellipse at 55% 48%, #c4b5fd 0%, #7c3aed 40%, transparent 72%);
          animation: blobMorphA 24s ease-in-out infinite;
        }
        .base-blob-b {
          position: absolute;
          width: 65%; height: 70%;
          top: 5%; right: -10%;
          border-radius: 44% 56% 38% 62% / 58% 44% 56% 42%;
          background: radial-gradient(ellipse at 46% 52%, #e0e7ff 0%, #818cf8 42%, transparent 72%);
          animation: blobMorphB 28s ease-in-out infinite;
          animation-delay: -8s;
        }
        .base-blob-c {
          position: absolute;
          width: 60%; height: 60%;
          bottom: -5%; left: 25%;
          border-radius: 55% 45% 66% 34% / 38% 62% 38% 62%;
          background: radial-gradient(ellipse at 50% 46%, #a5b4fc 0%, #4f46e5 44%, transparent 72%);
          animation: blobMorphC 22s ease-in-out infinite;
          animation-delay: -14s;
        }

        /* ═══════════════════════════════════════════════════════════════════
           LAYER 2 — Color motion  (z-index 2, blur 90px)
        ═══════════════════════════════════════════════════════════════════ */
        .layer-motion {
          position: absolute;
          inset: -20%;
          z-index: 2;
          will-change: transform;
          animation: motionFloat 20s ease-in-out infinite;
          filter: blur(90px);
          opacity: 0.65;
          mix-blend-mode: screen;
        }
        .motion-blob-a {
          position: absolute;
          width: 52%; height: 50%;
          top: 10%; left: 5%;
          border-radius: 48% 52% 44% 56% / 56% 44% 60% 40%;
          background: radial-gradient(ellipse at 52% 46%, #f0f4ff 0%, #c7d2fe 40%, rgba(99,102,241,0.6) 70%, transparent 90%);
          animation: floatA 18s ease-in-out infinite;
        }
        .motion-blob-b {
          position: absolute;
          width: 46%; height: 52%;
          top: 38%; right: 4%;
          border-radius: 60% 40% 52% 48% / 42% 58% 40% 60%;
          background: radial-gradient(ellipse at 48% 52%, #ddd6fe 0%, #8b5cf6 48%, transparent 74%);
          animation: floatB 22s ease-in-out infinite;
          animation-delay: -5s;
        }
        .motion-blob-c {
          position: absolute;
          width: 44%; height: 46%;
          bottom: 8%; left: 32%;
          border-radius: 38% 62% 56% 44% / 62% 38% 52% 48%;
          background: radial-gradient(ellipse at 46% 50%, #bfdbfe 0%, #6366f1 48%, transparent 74%);
          animation: floatC 17s ease-in-out infinite;
          animation-delay: -10s;
        }

        /* ═══════════════════════════════════════════════════════════════════
           LAYER 3 — Accent blobs  (z-index 3, blur 55px)
        ═══════════════════════════════════════════════════════════════════ */
        .layer-accent {
          position: absolute;
          inset: -10%;
          z-index: 3;
          will-change: transform;
          filter: blur(55px);
          opacity: 0.6;
          mix-blend-mode: screen;
        }
        .accent-blob-a {
          position: absolute;
          width: 30%; height: 32%;
          top: 8%; left: 14%;
          border-radius: 54% 46% 42% 58% / 46% 54% 58% 42%;
          background: radial-gradient(ellipse at 50% 50%, rgba(240,240,255,0.90) 0%, rgba(167,139,250,0.65) 50%, transparent 78%);
          animation: accentA 15s ease-in-out infinite;
        }
        .accent-blob-b {
          position: absolute;
          width: 28%; height: 30%;
          top: 50%; right: 10%;
          border-radius: 42% 58% 60% 40% / 58% 42% 52% 48%;
          background: radial-gradient(ellipse at 50% 50%, rgba(199,210,254,0.88) 0%, rgba(79,70,229,0.62) 48%, transparent 76%);
          animation: accentB 13s ease-in-out infinite;
          animation-delay: -4s;
        }
        .accent-blob-c {
          position: absolute;
          width: 26%; height: 28%;
          bottom: 15%; left: 40%;
          border-radius: 58% 42% 46% 54% / 40% 60% 40% 60%;
          background: radial-gradient(ellipse at 50% 50%, rgba(224,231,255,0.85) 0%, rgba(139,92,246,0.58) 50%, transparent 76%);
          animation: accentC 16s ease-in-out infinite;
          animation-delay: -8s;
        }

        /* ═══════════════════════════════════════════════════════════════════
           LAYER 4 — Soft light overlay  (z-index 4)
        ═══════════════════════════════════════════════════════════════════ */
        .layer-overlay {
          position: absolute;
          inset: 0;
          z-index: 4;
          pointer-events: none;
          background:
            radial-gradient(ellipse 80% 40% at 50% -5%, rgba(255,255,255,0.06) 0%, transparent 65%),
            radial-gradient(ellipse 60% 30% at 50% 105%, rgba(60,40,140,0.12) 0%, transparent 65%),
            linear-gradient(180deg, rgba(255,255,255,0.025) 0%, rgba(0,0,0,0.18) 100%);
          mix-blend-mode: overlay;
        }

        /* ═══════════════════════════════════════════════════════════════════
           CURSOR GLOW — z-index 5
        ═══════════════════════════════════════════════════════════════════ */
        .cursor-glow {
          position: absolute;
          width: 420px; height: 420px;
          border-radius: 50%;
          pointer-events: none;
          z-index: 5;
          transform: translate(-50%, -50%);
          background: radial-gradient(circle,
            rgba(220,220,255,0.13) 0%,
            rgba(139,92,246,0.07) 40%,
            transparent 72%);
          filter: blur(36px);
          mix-blend-mode: screen;
          will-change: left, top;
        }

        /* ═══════════════════════════════════════════════════════════════════
           NOISE GRAIN — z-index 9
        ═══════════════════════════════════════════════════════════════════ */
        .grain {
          position: absolute;
          inset: 0;
          z-index: 9;
          pointer-events: none;
          opacity: 0.035;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
          background-size: 200px 200px;
          mix-blend-mode: overlay;
        }

        /* ═══════════════════════════════════════════════════════════════════
           KEYFRAMES — faster durations throughout
        ═══════════════════════════════════════════════════════════════════ */
        @keyframes baseFloat {
          0%,100% { transform: translate3d(0,0,0) scale(1); }
          33%     { transform: translate3d(3%,2%,0) scale(1.04); }
          66%     { transform: translate3d(-2%,-3%,0) scale(0.98); }
        }
        @keyframes motionFloat {
          0%,100% { transform: translate3d(0,0,0) rotate(0deg); }
          40%     { transform: translate3d(-2%,3%,0) rotate(3deg); }
          72%     { transform: translate3d(2%,-2%,0) rotate(-2deg); }
        }
        @keyframes blobMorphA {
          0%,100% { border-radius: 62% 38% 55% 45% / 48% 60% 40% 52%; transform: translate(0,0) scale(1); }
          38%     { border-radius: 44% 56% 42% 58% / 58% 44% 54% 46%; transform: translate(3%,-4%) scale(1.07); }
          74%     { border-radius: 52% 48% 66% 34% / 40% 58% 44% 56%; transform: translate(-4%,5%) scale(1.03); }
        }
        @keyframes blobMorphB {
          0%,100% { border-radius: 44% 56% 38% 62% / 58% 44% 56% 42%; transform: translate(0,0) scale(1); }
          46%     { border-radius: 58% 42% 54% 46% / 44% 56% 40% 60%; transform: translate(-4%,3%) scale(1.1); }
          78%     { border-radius: 36% 64% 48% 52% / 62% 38% 52% 48%; transform: translate(5%,-5%) scale(0.96); }
        }
        @keyframes blobMorphC {
          0%,100% { border-radius: 55% 45% 66% 34% / 38% 62% 38% 62%; transform: translate(0,0) scale(1); }
          36%     { border-radius: 46% 54% 40% 60% / 56% 44% 62% 38%; transform: translate(5%,4%) scale(1.06); }
          70%     { border-radius: 62% 38% 52% 48% / 44% 56% 40% 60%; transform: translate(-3%,-4%) scale(1.04); }
        }
        @keyframes floatA {
          0%,100% { transform: translate(0,0) scale(1) rotate(0deg); }
          44%     { transform: translate(5%,-6%) scale(1.1) rotate(8deg); }
          78%     { transform: translate(-4%,5%) scale(0.96) rotate(-6deg); }
        }
        @keyframes floatB {
          0%,100% { transform: translate(0,0) scale(1) rotate(0deg); }
          36%     { transform: translate(-6%,4%) scale(1.12) rotate(-7deg); }
          72%     { transform: translate(5%,-5%) scale(0.98) rotate(6deg); }
        }
        @keyframes floatC {
          0%,100% { transform: translate(0,0) scale(1) rotate(0deg); }
          48%     { transform: translate(4%,6%) scale(1.08) rotate(5deg); }
          80%     { transform: translate(-5%,-4%) scale(1.04) rotate(-8deg); }
        }
        @keyframes accentA {
          0%,100% { transform: translate(0,0) scale(1); filter: blur(55px) hue-rotate(0deg); }
          42%     { transform: translate(8%,-7%) scale(1.14); filter: blur(55px) hue-rotate(18deg); }
          74%     { transform: translate(-6%,8%) scale(0.94); filter: blur(55px) hue-rotate(-14deg); }
        }
        @keyframes accentB {
          0%,100% { transform: translate(0,0) scale(1); filter: blur(55px) hue-rotate(0deg); }
          38%     { transform: translate(-7%,5%) scale(1.12); filter: blur(55px) hue-rotate(-20deg); }
          70%     { transform: translate(6%,-6%) scale(0.97); filter: blur(55px) hue-rotate(16deg); }
        }
        @keyframes accentC {
          0%,100% { transform: translate(0,0) scale(1); filter: blur(55px) hue-rotate(0deg); }
          46%     { transform: translate(5%,7%) scale(1.1); filter: blur(55px) hue-rotate(12deg); }
          76%     { transform: translate(-8%,-5%) scale(0.96); filter: blur(55px) hue-rotate(-18deg); }
        }

        @media (prefers-reduced-motion: reduce) {
          .layer-base, .layer-motion, .layer-accent,
          .base-blob-a, .base-blob-b, .base-blob-c,
          .motion-blob-a, .motion-blob-b, .motion-blob-c,
          .accent-blob-a, .accent-blob-b, .accent-blob-c {
            animation: none !important;
          }
        }
      `}</style>

      <div className="gradient-bg" aria-hidden="true">
        {/* Layer 1 — Base glow (180px blur) */}
        <div ref={slowLayerRef} className="layer-base">
          <div className="base-blob-a" />
          <div className="base-blob-b" />
          <div className="base-blob-c" />
        </div>

        {/* Layer 2 — Color motion (90px blur) */}
        <div ref={midLayerRef} className="layer-motion">
          <div className="motion-blob-a" />
          <div className="motion-blob-b" />
          <div className="motion-blob-c" />
        </div>

        {/* Layer 3 — Accent blobs (55px blur, hue-shift) */}
        <div ref={fastLayerRef} className="layer-accent">
          <div className="accent-blob-a" />
          <div className="accent-blob-b" />
          <div className="accent-blob-c" />
        </div>

        {/* Layer 4 — Soft light overlay */}
        <div className="layer-overlay" />

        {/* Cursor glow — instant tracking, no spring */}
        <div ref={glowRef} className="cursor-glow" />

        {/* Noise grain */}
        <div className="grain" />
      </div>
    </>
  );
}
