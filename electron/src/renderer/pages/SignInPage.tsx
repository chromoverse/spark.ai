import { useState } from "react";
import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import axiosInstance, { type ApiResponse } from "@/utils/axiosConfig";
import type { AuthResponse } from "@shared/auth.types";
import { toast } from "sonner";
import { useAppDispatch } from "@/store/hooks";
import { getCurrentUser } from "@/store/features/auth/authThunks";
import MinimalHeader from "@/components/local/MinimalHeader";

function SignInPage() {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [emailError, setEmailError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const validateEmail = (email: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

  const handleEmailSubmit = async () => {
    setEmailError("");
    if (!email) { setEmailError("Email is required"); return; }
    if (!validateEmail(email)) { setEmailError("Invalid email"); return; }

    setIsLoading(true);
    try {
      const response: ApiResponse = await axiosInstance.post("/auth/sign-in", { email });
      if (response.success) setStep(2);
      if (response.data) toast.success(response.data.message || response.message);
    } catch (error) {
      console.error("Sign in error:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleOtpSubmit = async () => {
    if (!otp || otp.length !== 6) return;
    setIsLoading(true);
    try {
      const data: AuthResponse = await axiosInstance.post("/auth/verify-otp", { email, otp });
      if (data.access_token && data.refresh_token) {
        await window.electronApi.saveToken("access_token", data.access_token);
        await window.electronApi.saveToken("refresh_token", data.refresh_token);
        await dispatch(getCurrentUser());
        await window.electronApi.onAuthSuccess();
        navigate("/home", { replace: true });
      }
    } catch (error: any) {
      toast.error(error?.error?.message || "Verification failed");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="h-screen w-screen bg-[#0a0a0f] text-white flex flex-col select-none">
      <MinimalHeader />
      <div className="flex-1 flex items-center justify-center">
        <div className="w-full max-w-sm px-6">
          {/* Back */}
          <button
            onClick={() => step === 1 ? navigate("/welcome") : (setStep(1), setOtp(""))}
            className="mb-6 text-slate-400 hover:text-white flex items-center gap-2 text-sm transition-colors"
          >
            <ArrowLeft size={16} /> Back
          </button>

          <h1 className="text-2xl font-semibold mb-2">
            {step === 1 ? "Sign In" : "Verify Email"}
          </h1>
          <p className="text-slate-400 text-sm mb-8">
            {step === 1
              ? "Enter your email to continue"
              : <>Code sent to <span className="text-white">{email}</span></>}
          </p>

          {step === 1 ? (
            <div className="space-y-4">
              <div>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => { setEmail(e.target.value); setEmailError(""); }}
                  onKeyDown={(e) => e.key === "Enter" && handleEmailSubmit()}
                  className="w-full px-4 py-3 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
                  placeholder="you@example.com"
                  disabled={isLoading}
                />
                {emailError && <p className="mt-1.5 text-xs text-red-400">{emailError}</p>}
              </div>
              <button
                onClick={handleEmailSubmit}
                disabled={isLoading}
                className="w-full py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
              >
                {isLoading ? "Sending..." : "Continue"}
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="relative">
                <input
                  type="text"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  onKeyDown={(e) => e.key === "Enter" && otp.length === 6 && handleOtpSubmit()}
                  className="w-full px-4 py-3 bg-slate-900 border border-slate-700 rounded-lg text-white text-center text-2xl tracking-[0.4em] font-mono placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
                  placeholder="000000"
                  maxLength={6}
                  disabled={isLoading}
                />
                {otp.length === 6 && (
                  <CheckCircle2 size={18} className="absolute right-3 top-1/2 -translate-y-1/2 text-green-400" />
                )}
              </div>
              <button
                onClick={handleOtpSubmit}
                disabled={isLoading || otp.length !== 6}
                className="w-full py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
              >
                {isLoading ? "Verifying..." : "Verify"}
              </button>
              <button
                onClick={handleEmailSubmit}
                className="w-full text-xs text-slate-500 hover:text-slate-300 transition-colors"
                disabled={isLoading}
              >
                Resend code
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default SignInPage;
