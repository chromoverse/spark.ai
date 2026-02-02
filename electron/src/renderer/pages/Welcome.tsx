import AuthLanderBg from "../../assets/AuthLanderBg.jpg";
import SparkIcon from "../../assets/icon.png";
import MinimalHeader from "@/components/local/MinimalHeader";
import { useNavigate } from "react-router-dom";
import { RippleButton } from "@/components/ui/ripple-button";

import Icon from "../../assets/icon.png"
import {toast} from "sonner"
import { useAppDispatch } from "@/store/hooks";



function Title() {
  return (
    <div className="webkit-drag-nodrag flex items-center mr-10 mt-10">
      <img src={SparkIcon} className="mt-8 w-16 lg:w-35" />
      <span className="relative font-science text-black/75 lg:text-8xl md:text-6xl text-4xl font-bold mt-10">
        S P A R K
        <span className="webkit-drag-nodrag text-[12px] absolute top-0 border-2 rounded-full p-1 hover:scale-110 right-[-25px]">
          AI
        </span>
      </span>
    </div>
  );
}

function DescribeApp() {
  return (
    <div className="webkit-drag-nodrag mt-5 text-gray-800/75 lg:text-2xl md:text-xl text-lg font-medium">
      Your Personal AI Assistant for Effortless Productivity
    </div>
  );
}

function EntranceMaker() {
  const navigate = useNavigate();
  return (
    <div className="webkit-drag-nodrag mt-60 flex flex-col gap-4 items-center">
      <RippleButton
        onClick={() => navigate("/auth/sign-up")}
        rippleColor="#ADD8E6"
      >
        Create a new Account
      </RippleButton>
      <span className="text-gray-800 text-[15px]">
        Already have an Account?{" "}
        <span onClick={() => navigate("/auth/sign-in")} className="hover:underline cursor-pointer">Login</span>
      </span>
    </div>
  );
}


interface WelcomeProps {
  isLoading?: boolean;
}

export default function Welcome({ isLoading = false }: WelcomeProps) {
  const dispatch = useAppDispatch()
  
  return (
    <div
      className="h-screen w-screen webkit-drag-drag select-none"
      style={{
        backgroundImage: `url(${AuthLanderBg})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      <div className="w-full h-full flex items-center relative flex-col backdrop-blur-xs">
        <MinimalHeader />
        <Title />
        <DescribeApp />
        
        {isLoading ? (
          <div className="mt-60 flex flex-col gap-4 items-center">
             <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
             <span className="text-gray-600 font-medium">Initializing...</span>
          </div>
        ) : (
          <EntranceMaker />
        )}

        <span className="absolute bottom-5 text-sm text-gray-900">V.1.0.0</span>
      </div>
    </div>
  );
}
