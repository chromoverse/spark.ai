import Header from "@/components/local/Header";
import BottomBar from "@/components/local/bottomBar/BottomBar";
import Sidebar, { type SidebarItem } from "@/components/local/home/Sidebar";
import JobsPanel from "@/components/local/home/JobsPanel";
import { useAiResponseHandler } from "@/hooks/useAiResponseHandler";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import type { EntityCardData } from "@/components/local/home/EntityCards";
import type { TaskOutput } from "@shared/socket.types";

const SparkLogs = lazy(() => import("./home/SparkLogs"));
const History = lazy(() => import("./home/History"));
const SettingsPage = lazy(() => import("./home/SettingsPage"));
const Connectors = lazy(() => import("./home/Connectors"));
const Automation = lazy(() => import("./home/Automation"));
const Bookings = lazy(() => import("./home/Bookings"));
const ToolsPage = lazy(() => import("./home/ToolsPage"));
const PluginsPage = lazy(() => import("./home/PluginsPage"));
const SkillsPage = lazy(() => import("./home/SkillsPage"));
const PermissionsPage = lazy(() => import("./home/PermissionsPage"));
const HomeLive = lazy(() => import("./home/HomeLive"));

function PageLoader() {
  return <div className="flex items-center justify-center h-full"><div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>;
}

interface EntityResult {
  entities: EntityCardData[];
  intent: string;
}

function Home() {
  const [activeTab, setActiveTab] = useState<SidebarItem>("home");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showJobs, setShowJobs] = useState(false);
  const [entityResult, setEntityResult] = useState<EntityResult | null>(null);

  useEffect(() => {
    const cleanup = window.electronApi?.onSparkNavigate?.((payload) => {
      if (payload?.tab) setActiveTab(payload.tab as SidebarItem);
    });
    return () => { cleanup?.(); };
  }, []);

  const handleTaskBatchComplete = useCallback((results: TaskOutput[]) => {
    console.log("Tasks completed:", results);
    for (const result of results) {
      if (
        result.success &&
        result.data?.result_type === "entities" &&
        Array.isArray(result.data?.entities) &&
        result.data.entities.length > 0
      ) {
        setEntityResult({
          entities: result.data.entities as EntityCardData[],
          intent: result.data.intent ?? "results",
        });
        break;
      }
    }
  }, []);

  useAiResponseHandler({
    autoListen: true,
    onPQHSuccess: (payload) => console.log("PQH completed:", payload),
    onTaskBatchComplete: handleTaskBatchComplete,
    onTaskBatchError: (error) => console.error("Tasks failed:", error),
  });

  const renderContent = () => {
    switch (activeTab) {
      case "home": return (
        <HomeLive
          entityResult={entityResult}
          onEntityDismiss={() => setEntityResult(null)}
          showJobs={showJobs}
          onToggleJobs={() => setShowJobs(c => !c)}
        />
      );
      case "history": return <History />;
      case "spark-logs": return <SparkLogs />;
      case "tools": return <ToolsPage />;
      case "plugins": return <PluginsPage />;
      case "skills": return <SkillsPage />;
      case "permissions": return <PermissionsPage />;
      case "settings": return <SettingsPage />;
      case "connectors": return <Connectors />;
      case "automation": return <Automation />;
      case "bookings": return <Bookings />;
    }
  };

  return (
    <div
      className="h-screen w-screen overflow-hidden flex"
      style={{ background: "var(--sp-bg)", color: "var(--sp-ink)", fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif" }}
    >
      {/* Sidebar spans full height */}
      <Sidebar
        active={activeTab}
        onChange={setActiveTab}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(c => !c)}
      />

      {/* Right column: header + content + status bar */}
      <div className="flex-1 flex flex-col min-w-0">
        <Header />
        <div className="flex-1 flex min-h-0 overflow-hidden">
          <main className="flex-1 min-h-0 overflow-hidden">
            <Suspense fallback={<PageLoader />}>
              {renderContent()}
            </Suspense>
          </main>
          {activeTab === "home" && <JobsPanel show={showJobs} />}
        </div>
        <BottomBar />
      </div>
    </div>
  );
}

export default Home;
