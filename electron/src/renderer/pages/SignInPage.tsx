import { useState } from "react";
import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAppDispatch } from "@/store/hooks";
import { getCurrentUser } from "@/store/features/auth/authThunks";
import MinimalHeader from "@/components/local/MinimalHeader";

// Signs in (or up) against the v2 brain: an email code or Google. Tokens stay in the main
// process; this page only sees the brain's persona-voiced messages.

type Busy = "idle" | "sending" | "verifying" | "google";

const isEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);

function SignInPage() {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<Busy>("idle");

  const finish = async () => {
    await dispatch(getCurrentUser());
    await window.electronApi.onAuthSuccess();
    navigate("/home", { replace: true });
  };

  const sendCode = async () => {
    setError("");
    setNotice("");
    if (!email.trim()) return setError("Pop your email in first.");
    if (!isEmail(email.trim())) return setError("That email doesn't look right. Mind checking it?");
    setBusy("sending");
    const res = await window.electronApi.brain.otpStart(email.trim());
    setBusy("idle");
    if (!res.ok) return setError(res.error.message);
    setStep("code");
    setNotice("Code's on its way. It works for 10 minutes.");
  };

  const verify = async () => {
    if (code.length !== 6) return;
    setError("");
    setBusy("verifying");
    const res = await window.electronApi.brain.otpVerify(email.trim(), code);
    if (!res.ok) {
      setBusy("idle");
      setCode("");
      return setError(res.error.message);
    }
    await finish();
  };

  const google = async () => {
    setError("");
    setNotice("Finish signing in in your browser, then come back here.");
    setBusy("google");
    const res = await window.electronApi.brain.googleSignIn();
    if (!res.ok) {
      setBusy("idle");
      setNotice("");
      return setError(res.error.message);
    }
    await finish();
  };

  const isBusy = busy !== "idle";
  const back = () => {
    if (step === "email") return navigate("/welcome");
    setStep("email");
    setCode("");
    setError("");
    setNotice("");
  };

  return (
    <div className="h-screen w-screen bg-[#0a0a0f] text-white flex flex-col select-none">
      <MinimalHeader />
      <div className="flex-1 flex items-center justify-center">
        <div className="w-full max-w-sm px-6">
          <button
            onClick={back}
            disabled={isBusy}
            className="mb-6 text-white/40 hover:text-white flex items-center gap-2 text-sm transition-colors disabled:opacity-50"
          >
            <ArrowLeft size={16} /> Back
          </button>

          <h1 className="text-2xl font-semibold mb-2">
            {step === "email" ? "Sign in to Spark" : "Check your email"}
          </h1>
          <p className="text-white/40 text-sm mb-8">
            {step === "email" ? (
              "New here? Same steps, and we'll set you up."
            ) : (
              <>
                Enter the 6-digit code we sent to <span className="text-white">{email.trim()}</span>
              </>
            )}
          </p>

          {step === "email" ? (
            <div className="space-y-4">
              <label className="block">
                <span className="sr-only">Email</span>
                <input
                  type="email"
                  autoFocus
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    setError("");
                  }}
                  onKeyDown={(e) => e.key === "Enter" && !isBusy && sendCode()}
                  className="w-full px-4 py-3 bg-[#0f0f16] border border-white/10 rounded-lg text-white placeholder-white/25 focus:outline-none focus:border-[#d97757] transition-colors"
                  placeholder="you@example.com"
                  disabled={isBusy}
                />
              </label>
              <button
                onClick={sendCode}
                disabled={isBusy}
                className="w-full py-3 bg-[#d97757] hover:bg-[#c96847] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
              >
                {busy === "sending" ? "Sending…" : "Email me a code"}
              </button>
              <div className="flex items-center gap-3 text-white/25 text-xs">
                <span className="h-px flex-1 bg-white/10" /> or <span className="h-px flex-1 bg-white/10" />
              </div>
              <button
                onClick={google}
                disabled={isBusy}
                className="w-full py-3 border border-white/15 hover:border-white/30 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
              >
                {busy === "google" ? "Waiting for Google…" : "Continue with Google"}
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="relative">
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  aria-label="6-digit code"
                  value={code}
                  onChange={(e) => {
                    setCode(e.target.value.replace(/\D/g, "").slice(0, 6));
                    setError("");
                  }}
                  onKeyDown={(e) => e.key === "Enter" && code.length === 6 && !isBusy && verify()}
                  className="w-full px-4 py-3 bg-[#0f0f16] border border-white/10 rounded-lg text-white text-center text-2xl tracking-[0.4em] font-mono placeholder-white/25 focus:outline-none focus:border-[#d97757] transition-colors"
                  placeholder="000000"
                  maxLength={6}
                  disabled={isBusy}
                />
                {code.length === 6 && (
                  <CheckCircle2 size={18} className="absolute right-3 top-1/2 -translate-y-1/2 text-green-400" />
                )}
              </div>
              <button
                onClick={verify}
                disabled={isBusy || code.length !== 6}
                className="w-full py-3 bg-[#d97757] hover:bg-[#c96847] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
              >
                {busy === "verifying" ? "Checking…" : "Sign in"}
              </button>
              <button
                onClick={sendCode}
                className="w-full text-xs text-white/30 hover:text-white/60 transition-colors disabled:opacity-50"
                disabled={isBusy}
              >
                {busy === "sending" ? "Sending…" : "Send a new code"}
              </button>
            </div>
          )}

          <div className="mt-4 min-h-5 text-xs" aria-live="polite">
            {error ? <p className="text-red-400">{error}</p> : notice && <p className="text-white/50">{notice}</p>}
          </div>
        </div>
      </div>
    </div>
  );
}

export default SignInPage;
