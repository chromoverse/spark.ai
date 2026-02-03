import { Button } from '@/components/ui/button'
import { useSocket } from '@/context/socketContextProvider'
import React from 'react'
import axios from "axios"
import { useSparkTTS } from '@/context/sparkTTSContext'
import ServerStatusShower from '../terminals/ServerStatusTerminal'

import { tokenRefreshManager } from "@/lib/auth/tokenRefreshManager";
import type { TaskRecord } from "@shared/socket.types";



export default function CenterPanel() {
  const { socket, isConnected, on, emit, off } = useSocket()
  const { speak, stop, isSpeaking } = useSparkTTS();
   const [status, setStatus] = React.useState<string>("Not started");
  
  const getAudio = async(text:string | undefined) => {
    console.log("htting api now")
   const res = await axios.post(
     `${import.meta.env.VITE_API_BASE_URL}/api/tts`,
     {
       text: text,
     },
     { responseType: "arraybuffer" }
   );
    
    console.log("REs", res)
   const audioBlob = new Blob([res.data], { type: "audio/mpeg" });
   const audioUrl = URL.createObjectURL(audioBlob);

   const audio = new Audio(audioUrl);
   audio.play();
  }

  // TaskRecord for opening camera
  const cameraTask: TaskRecord = {
    task: {
      taskId: "task_open_camera_001",
      tool: "open_app",
      executionTarget: "client",
      dependsOn: [],
      inputs: {
        target: "camera"
      },
      inputBindings: {},
      lifecycleMessages: {
        onStart: "Opening camera...",
        onSuccess: "Camera opened successfully!",
        onFailure: "Failed to open camera"
      },
      control: {
        onFailure: "continue",
        timeoutMs: 30000
      }
    },
    status: "pending",
    resolvedInputs: {
      target: "camera"
    },
    createdAt: new Date().toISOString()
  }
  

  

  const play = () => {
    speak(
      "कोई बात नहीं है, सर। सब ठीक हो जाएगा। क्या हुआ जो इतनी माफी मांग रहे हैं?"
    );
  }

  const openCamera = async () => {
    try {
       console.log("🟢 Calling window.electronApi.executeTasks with camera task...");
      
       const res = await window.electronApi.executeTasks([cameraTask]);

       console.log("🟢 Response received:", res);
       setStatus(`Response: ${JSON.stringify(res)}`);

       if (res.status === "ok") {
         console.log("✅ Camera opened:", res);
       } else {
         console.error("❌ Failed to open camera:", res.message);
       }
    } catch (error) {
      console.error("❌ Error opening camera:", error);
      setStatus(`Error: ${error}`);
    }
  }

  // ✅ FIX: Prevent page refresh
const handleRefreshToken = async (e: React.MouseEvent<HTMLButtonElement>) => {
  e.preventDefault(); // Prevent any default behavior
  try {
    console.log("hitting api now")
    const res = await tokenRefreshManager.refreshAccessToken();
    console.log(
      "after hitting res"
    )
  } catch (error) {
    console.error("Token refresh failed:", error);
  }
  }
  

  function testWebSocket() {
    emit("request-tts", {
      text: "Sir everything ready now. How was your day tough. I am here to help you with your work.  ",
      userId: "test-user-123",
    });
  }

  
  return (
    <div>
      <Button onClick={() => getAudio("हो गया सर, देख सकते हैं। कुछ और चाहिए?")}>get Audio Http</Button>
      <Button onClick={() => play()}>play ws sound</Button>
      <Button 
        type="button"
        className="webkit-drag-nodrag" 
        onClick={handleRefreshToken}
        >
        Refresh Token
      </Button>
      <Button 
        type="button"
        className="webkit-drag-nodrag" 
        onClick={testWebSocket}
        >
        Test WebSocket
      </Button>
      <Button 
        type="button"
        className="webkit-drag-nodrag bg-blue-600 hover:bg-blue-700 ml-2" 
        onClick={openCamera}
        >
        📷 Open Camera
      </Button>
      <div className="mt-4 p-2 bg-gray-900 rounded">
        <p className="text-sm">Status: {status}</p>
        <ServerStatusShower />
      </div>
    </div>
  );
}
