import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, Cpu, Home as HomeIcon, Settings, Sparkles } from "lucide-react";
import Header from "@/components/local/Header";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { resetUser } from "@/store/features/auth/authSlice";
import { ACTIVE, currentJob } from "@/store/features/spark/sparkSlice";
import { useEar } from "@/hooks/useEar";
import HomePage from "./spark/HomePage";
import ActivityPage from "./spark/ActivityPage";
import CapabilitiesPage from "./spark/CapabilitiesPage";
import EnginesHub from "./spark/EnginesHub";
import SettingsHub, { SECTIONS, type Section } from "./spark/SettingsHub";
import Palette from "./spark/Palette";
import type { Command } from "./spark/logic";

// The main window (DESIGN.md §3, docs/mockups/r2-ui.html): five destinations on a left rail,
// Ctrl+K for everything. The voice overlay (pages/overlay) is the other half of the UI.

type Dest = "home" | "activity" | "capabilities" | "engines" | "settings";

const RAIL: { id: Dest; label: string; icon: ReactNode }[] = [
  { id: "home", label: "Home", icon: <HomeIcon className="size-[18px]" strokeWidth={1.8} /> },
  { id: "activity", label: "Activity", icon: <Activity className="size-[18px]" strokeWidth={1.8} /> },
  { id: "capabilities", label: "Capabilities", icon: <Sparkles className="size-[18px]" strokeWidth={1.8} /> },
  { id: "engines", label: "Engines", icon: <Cpu className="size-[18px]" strokeWidth={1.8} /> },
  { id: "settings", label: "Settings", icon: <Settings className="size-[18px]" strokeWidth={1.8} /> },
];

// v1 deep links (tray, notifications) still name old tabs
const LEGACY: Record<string, Dest> = { history: "activity", "spark-logs": "activity", tools: "capabilities", permissions: "settings" };

export default function Home() {
  const [dest, setDest] = useState<Dest>("home");
  const [section, setSection] = useState<Section>("account");
  const [palette, setPalette] = useState(false);
  const spark = useAppSelector((s) => s.spark);
  const user = useAppSelector((s) => s.auth.user);
  const ear = useEar();
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const job = currentJob(spark);
  const live = job && ACTIVE.includes(job.status) ? job : null;

  useEffect(() => {
    const off = window.electronApi.onSparkNavigate?.(({ tab }) => {
      const d = (RAIL.find((r) => r.id === tab)?.id ?? LEGACY[tab]) as Dest | undefined;
      if (d) setDest(d);
    });
    const key = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
    };
    window.addEventListener("keydown", key);
    return () => {
      off?.();
      window.removeEventListener("keydown", key);
    };
  }, []);

  const commands = useMemo<Command[]>(() => {
    const go = (d: Dest) => () => setDest(d);
    const open = (s: Section) => () => {
      setSection(s);
      setDest("settings");
    };
    return [
      ...RAIL.map((r) => ({ id: `go-${r.id}`, group: "Go to", label: r.label, run: go(r.id) })),
      ...SECTIONS.map((s) => ({ id: `set-${s.id}`, group: "Settings", label: s.label, keywords: s.id === "permissions" ? "rules mode approvals" : s.id === "privacy" ? "verbosity training name" : s.id === "memory" ? "remember forget learned" : "", run: open(s.id) })),
      ...(live ? [{ id: "stop", group: "Actions", label: `Stop: ${live.title}`, keywords: "cancel job", run: () => void window.electronApi.brain.cancelJob(live.id) }] : []),
      { id: "mic", group: "Actions", label: ear.listening ? "Turn the mic off" : "Turn the mic on", keywords: "listen ear voice", run: ear.toggle },
      { id: "stop-voice", group: "Actions", label: "Stop talking", keywords: "quiet silence", run: () => void window.electronApi.voice.stop() },
      { id: "bench", group: "Actions", label: "Run engine benchmark", keywords: "voice speed", run: () => {
        setDest("engines");
        void window.electronApi.engines.runBenchmark();
      } },
      { id: "signout", group: "Actions", label: "Sign out", keywords: "log out", run: () => {
        void window.electronApi.brain.signOut().then(() => {
          dispatch(resetUser());
          navigate("/welcome");
        });
      } },
    ];
  }, [live, ear.listening, ear.toggle, dispatch, navigate]);

  return (
    <div className="sp-sans flex h-screen w-screen overflow-hidden bg-[var(--sp-bg)] text-[var(--sp-ink)]">
      <aside className="flex w-[76px] shrink-0 flex-col items-center gap-1 border-r border-[var(--sp-line)] py-3">
        <div className="sp-orb mb-3 size-7 rounded-full" data-mode="idle" aria-hidden />
        {RAIL.map((r) => (
          <button
            key={r.id}
            onClick={() => setDest(r.id)}
            aria-current={dest === r.id ? "page" : undefined}
            className={`relative flex w-[64px] flex-col items-center gap-1 rounded-xl py-2 text-[10.5px] transition-colors ${dest === r.id ? "bg-[var(--sp-bg-3)] text-[var(--sp-ink)]" : "text-[var(--sp-ink-3)] hover:text-[var(--sp-ink)]"}`}
          >
            {r.icon}
            {r.label}
            {r.id === "home" && (spark.approvals.length > 0 || spark.asks.length > 0) && <span className="absolute right-2 top-1.5 size-1.5 rounded-full bg-[var(--sp-warn)]" />}
          </button>
        ))}
        <div className="flex-1" />
        <button
          className="flex size-8 items-center justify-center rounded-full bg-[var(--sp-bg-3)] text-[12px] font-medium text-[var(--sp-ink-2)]"
          title={user?.email}
          onClick={() => {
            setSection("account");
            setDest("settings");
          }}
        >
          {(user?.fullName ?? user?.email ?? "?").slice(0, 1).toUpperCase()}
        </button>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <Header onPalette={() => setPalette(true)} />
        <main className="min-h-0 flex-1">
          {dest === "home" && <HomePage />}
          {dest === "activity" && <ActivityPage />}
          {dest === "capabilities" && <CapabilitiesPage />}
          {dest === "engines" && <EnginesHub />}
          {dest === "settings" && <SettingsHub section={section} onSection={setSection} />}
        </main>
      </div>
      {palette && <Palette commands={commands} onClose={() => setPalette(false)} />}
    </div>
  );
}
