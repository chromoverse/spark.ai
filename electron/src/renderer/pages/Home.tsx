import BottomBar from "@/components/local/bottomBar/BottomBar";
import Header from "@/components/local/Header";
import CenterPanel from "@/components/local/home/CenterPanel";
import LeftPanel from "@/components/local/home/LeftPanel";
import RightPanel from "@/components/local/home/RightPanel";
import TerminalShower from "@/components/local/terminals/TerminalShower";
import { useAiResponseHandler } from "@/hooks/useAiResponseHandler";
import { useAppSelector } from "@/store/hooks";

function Home() {
  const {user} = useAppSelector((state) => state.auth)
  console.log("user fomr state", user)
   useAiResponseHandler({
    autoListen: true,
    onPQHSuccess: (payload) => {
      console.log("PQH completed:", payload);
    },
    onTaskBatchComplete: (results) => {
      console.log("Tasks completed:", results);
      // Update UI, show notifications, etc.
    },
    onTaskBatchError: (error) => {
      console.error("Tasks failed:", error);
      // Show error toast
    }
  });

  return (
    <div className="h-screen w-screen bg-[#070818] text-white overflow-hidden flex flex-col justify-between">
      <Header />
      <div className="w-full h-[calc(100%-85px)] flex justify-between">
        <div className="h-full lg:w-[300px] w-60">
          <LeftPanel />
        </div>
        <div className="h-full flex-1 border-r border-l border-white/5">
          <CenterPanel />
        </div>
        <div className="h-full lg:w-[300px] w-60">
          <RightPanel />
        </div>
      </div>
      <BottomBar />
    </div>
  );
}

export default Home;
