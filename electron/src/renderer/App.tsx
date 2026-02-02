import { HashRouter, Route, Routes, Navigate } from "react-router-dom"
import { Toaster } from "@/components/ui/sonner";
import AppInitializer from "@/components/layout/AppInitializer";
import AuthGuard from "@/components/guards/AuthGuard";
import PublicGuard from "@/components/guards/PublicGuard";

// Pages
import Home from './pages/Home'
import Welcome from "./pages/Welcome";
import SignUp from "./pages/SignUp";
import SignInPage from "./pages/SignInPage";
import AiPanel from "./pages/AiPanel/AiPanel";

export default function App() {
  return (
    <HashRouter>
      <Toaster richColors />
      <AppInitializer>
        <Routes>
          {/* Public Routes */}
          <Route element={<PublicGuard />}>
            <Route path="/welcome" element={<Welcome />} />
            <Route path="/auth/sign-up" element={<SignUp />} />
            <Route path="/auth/sign-in" element={<SignInPage />} />
          </Route>

          {/* Protected Routes */}
          <Route element={<AuthGuard />}>
            <Route path="/" element={<Navigate to="/home" replace />} />
            <Route path="/home" element={<Home />} />
            <Route path="/ai-panel" element={<AiPanel />} />
          </Route>
          
          {/* Catch all - Redirect to welcome (which will handle auth check if actually valid) or just 404 */}
          <Route path="*" element={<Navigate to="/welcome" replace />} />
        </Routes>
      </AppInitializer>
    </HashRouter>
  );
}
