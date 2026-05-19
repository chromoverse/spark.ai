import SparkIcon from "../../assets/icon.png";
import MinimalHeader from "@/components/local/MinimalHeader";
import { useNavigate } from "react-router-dom";

interface WelcomeProps {
  isLoading?: boolean;
}

export default function Welcome({ isLoading = false }: WelcomeProps) {
  const navigate = useNavigate();

  return (
    <div className="h-screen w-screen select-none bg-[#0a0a0f] text-white flex flex-col">
      <MinimalHeader />
      <div className="flex-1 flex flex-col items-center justify-center gap-6">
        <img src={SparkIcon} className="w-16" />
        <h1 className="font-science text-5xl font-bold tracking-widest text-white/90">
          S P A R K
        </h1>
        <p className="text-slate-400 text-lg">
          Your Personal AI Assistant
        </p>

        {isLoading ? (
          <div className="mt-12 flex flex-col items-center gap-3">
            <div className="w-7 h-7 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-slate-500 text-sm">Initializing...</span>
          </div>
        ) : (
          <div className="mt-12 flex flex-col items-center gap-4">
            <button
              onClick={() => navigate("/auth/sign-up")}
              className="px-8 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
            >
              Create Account
            </button>
            <span
              onClick={() => navigate("/auth/sign-in")}
              className="text-sm text-slate-500 hover:text-white cursor-pointer transition-colors"
            >
              Sign In
            </span>
          </div>
        )}
      </div>
      <div className="text-center pb-4 flex flex-col items-center gap-1">
        <span className="text-xs text-slate-600">v1.0.0</span>
        <span className="text-[11px] text-slate-600">
          <span onClick={() => navigate("/privacy")} className="hover:text-slate-400 cursor-pointer transition-colors">Privacy Policy</span>
          {" · "}
          <span onClick={() => navigate("/about")} className="hover:text-slate-400 cursor-pointer transition-colors">About</span>
        </span>
      </div>
    </div>
  );
}
