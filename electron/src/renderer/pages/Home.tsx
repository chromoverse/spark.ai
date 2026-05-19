import Header from "@/components/local/Header";
import BottomBar from "@/components/local/bottomBar/BottomBar";
import Sidebar, { type SidebarItem } from "@/components/local/home/Sidebar";
import { useAiResponseHandler } from "@/hooks/useAiResponseHandler";
import { lazy, Suspense, useState } from "react";

const SparkLogs = lazy(() => import("./home/SparkLogs"));
const History = lazy(() => import("./home/History"));
const SettingsPage = lazy(() => import("./home/SettingsPage"));
const ExternalServices = lazy(() => import("./home/ExternalServices"));
const Automation = lazy(() => import("./home/Automation"));
const Bookings = lazy(() => import("./home/Bookings"));

function PageLoader() {
  return <div className="flex items-center justify-center h-full"><div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>;
}

function Home() {
  const [activeTab, setActiveTab] = useState<SidebarItem>("history");

  useAiResponseHandler({
    autoListen: true,
    onPQHSuccess: (payload) => console.log("PQH completed:", payload),
    onTaskBatchComplete: (results) => console.log("Tasks completed:", results),
    onTaskBatchError: (error) => console.error("Tasks failed:", error),
  });

  const renderContent = () => {
    switch (activeTab) {
      case "history": return <History />;
      case "spark-logs": return <SparkLogs />;
      case "settings": return <SettingsPage />;
      case "external-services": return <ExternalServices />;
      case "automation": return <Automation />;
      case "bookings": return <Bookings />;
    }
  };

  return (
    <div className="h-screen w-screen bg-[#0a0a0f] text-white overflow-hidden flex flex-col">
      <Header />
      <div className="flex-1 flex min-h-0">
        <Sidebar active={activeTab} onChange={setActiveTab} />
        <main className="flex-1 min-h-0 overflow-hidden">
          <Suspense fallback={<PageLoader />}>
            {renderContent()}
          </Suspense>
        </main>
      </div>
      <BottomBar />
    </div>
  );
}

export default Home;
