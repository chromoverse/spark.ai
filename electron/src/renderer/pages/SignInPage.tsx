import React, { useState } from "react";
import { ArrowLeft, Mail, Lock, CheckCircle2, Sparkles } from "lucide-react";
import { RippleButton } from "@/components/ui/ripple-button";
import { useNavigate } from "react-router-dom";
import AuthLanderBg from "../../assets/AuthLanderBg.jpg";
import axiosInstance, { type ApiResponse } from "@/utils/axiosConfig";
import type { AuthResponse } from "@shared/auth.types";
import { toast } from "sonner";
import { useAppDispatch } from "@/store/hooks";
import { verifyOtp } from "@/store/features/auth/authThunks";

function SignInPage() {
  const navigate = useNavigate();
  const dispatch = useAppDispatch()
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [emailError, setEmailError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const validateEmail = (email: string) => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  };

  const handleEmailSubmit = async () => {
    setEmailError("");

    if (!email) {
      setEmailError("Email is required");
      return;
    }

    if (!validateEmail(email)) {
      setEmailError("Please enter a valid email address");
      return;
    }

    setIsLoading(true);

    try {
      const response : ApiResponse = await axiosInstance.post("/auth/sign-in", { email });
      console.log("Signin response:", response);
      if(response.success){
        setStep(2);
      }
      if(response.data){
        toast.success(response.data.message || response.message)
      }
    } catch (error) {
      console.error("Error Signining:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleOtpSubmit = async () => {
    if (!otp || otp.length !== 6) {
      return;
    }

     try {
       const response : AuthResponse = await axiosInstance.post("/auth/verify-otp", {
         email,
         otp,
       });
       console.log("OTP verification response:", response);
       if (response.success) {
        navigate("/");
      }
     } catch (error) {
       console.error("Error verifying OTP:", error);
     }
  };


  const handleBack = () => {
    if (step === 1) {
      navigate("/");
    } else {
      setStep(1);
      setOtp("");
    }
  };

  const handleResendOtp = () => {
    // TODO: Add resend OTP action here
    console.log("Resend OTP");
  };

  return (
    <div
      className="h-screen w-screen webkit-drag-drag select-none overflow-hidden flex items-center justify-center p-4 relative"
      style={{
        backgroundImage: `url(${AuthLanderBg})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      {/* Animated background elements */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-20 left-10 w-72 h-72 bg-blue-300 rounded-full mix-blend-multiply filter blur-xl opacity-20 animate-blob" />
        <div className="absolute top-40 right-10 w-72 h-72 bg-purple-300 rounded-full mix-blend-multiply filter blur-xl opacity-20 animate-blob animation-delay-2000" />
        <div className="absolute -bottom-8 left-20 w-72 h-72 bg-indigo-300 rounded-full mix-blend-multiply filter blur-xl opacity-20 animate-blob animation-delay-4000" />
      </div>

      <div className="w-full max-w-md relative z-10 webkit-drag-nodrag select-none">
        <div
          className="rounded-3xl shadow-2xl p-8 relative backdrop-blur-xl overflow-hidden"
          style={{
            background: "rgba(255, 255, 255, 0.75)",
            borderColor: "rgba(173, 216, 230, 0.5)",
            boxShadow:
              "0 20px 60px rgba(0, 0, 0, 0.12), 0 0 100px rgba(173, 216, 230, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.6)",
          }}
        >
          {/* Header */}
          <div className="mb-8">
            <div className="flex items-center gap-3 mb-6">
              <button
                onClick={handleBack}
                className="text-gray-700 hover:text-blue-600 transition-all duration-300 p-2 rounded-xl hover:bg-white/60 hover:shadow-lg group"
                disabled={isLoading}
              >
                <ArrowLeft
                  size={22}
                  className="group-hover:-translate-x-1 transition-transform duration-300"
                />
              </button>
              <div className="flex items-center gap-2 flex-1">
                <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 bg-clip-text text-transparent">
                  {step === 1 ? "SignIn" : "Verify Email"}
                </h1>
              </div>
            </div>
            <p className="text-gray-600 text-sm flex items-center gap-2">
              {step === 1 ? (
                <>
                  <span>Enter your email address to get started</span>
                </>
              ) : (
                <>
                  <span>
                    We've sent a verification code to <strong>{email}</strong>
                  </span>
                </>
              )}
            </p>
          </div>

          {/* Step 1: Email Input */}
          <div
            className={`transition-all duration-500 ease-in-out ${
              step === 1
                ? "opacity-100 translate-x-0"
                : "opacity-0 translate-x-8 absolute pointer-events-none"
            }`}
          >
            <div className="space-y-6 select-text">
              <div>
                <label
                  htmlFor="email"
                  className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2"
                >
                  <Mail size={16} className="text-blue-500" />
                  Email address
                </label>
                <div className="relative">
                  <input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      setEmailError("");
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        handleEmailSubmit();
                      }
                    }}
                    className="w-full pl-4 pr-4 py-3 border-2 rounded-xl focus:ring-2 focus:ring-blue-400 focus:border-blue-400 outline-none transition-all backdrop-blur-sm text-black"
                    style={{
                      background: "rgba(255, 255, 255, 0.9)",
                      borderColor: emailError
                        ? "rgba(239, 68, 68, 0.5)"
                        : "rgba(173, 216, 230, 0.4)",
                      boxShadow: "0 4px 16px rgba(173, 216, 230, 0.15)",
                    }}
                    placeholder="you@example.com"
                    disabled={isLoading}
                  />
                </div>
                {emailError && (
                  <p className="mt-2 text-sm text-red-500 font-medium flex items-center gap-1">
                    <span className="w-1 h-1 bg-red-500 rounded-full" />
                    {emailError}
                  </p>
                )}
              </div>

              <RippleButton
                onClick={handleEmailSubmit}
                disabled={isLoading}
                className="w-full py-3.5 font-semibold"
                rippleColor="#93C5FD"
              >
                {isLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Sending...
                  </span>
                ) : (
                  <span className="flex items-center justify-center gap-2">
                    Continue
                    <ArrowLeft size={18} className="rotate-180" />
                  </span>
                )}
              </RippleButton>
            </div>
          </div>

          {/* Step 2: OTP Input */}
          <div
            className={`transition-all duration-500 ease-in-out ${
              step === 2
                ? "opacity-100 translate-x-0"
                : "opacity-0 -translate-x-8 absolute pointer-events-none"
            }`}
          >
            <div className="space-y-6">
              <div>
                <label
                  htmlFor="otp"
                  className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2"
                >
                  <Lock size={16} className="text-indigo-500" />
                  Verification code
                </label>
                <div className="relative">
                  <input
                    id="otp"
                    type="text"
                    value={otp}
                    onChange={(e) =>
                      setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && otp.length === 6) {
                        handleOtpSubmit();
                      }
                    }}
                    className="w-full px-4 py-4 border-2 rounded-xl focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-all text-center text-3xl tracking-widest font-bold backdrop-blur-sm"
                    style={{
                      background: "rgba(255, 255, 255, 0.9)",
                      borderColor: "rgba(173, 216, 230, 0.4)",
                      boxShadow: "0 4px 16px rgba(173, 216, 230, 0.15)",
                      color: "#4338ca",
                      letterSpacing: "0.5em",
                    }}
                    placeholder="● ● ● ● ● ●"
                    maxLength={6}
                    disabled={isLoading}
                  />
                  {otp.length === 6 && (
                    <CheckCircle2
                      size={24}
                      className="absolute right-4 top-1/2 -translate-y-1/2 text-green-500 animate-in fade-in zoom-in duration-300"
                    />
                  )}
                </div>
              </div>

              <RippleButton
                onClick={handleOtpSubmit}
                disabled={isLoading || otp.length !== 6}
                className="w-full py-3.5 font-semibold"
                rippleColor="#93C5FD"
              >
                {isLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Verifying...
                  </span>
                ) : (
                  <span className="flex items-center justify-center gap-2">
                    <CheckCircle2
                      size={24}
                      className={`${
                        otp.length === 6 ? "text-green-500 " : ""
                      } animate-in fade-in zoom-in duration-300`}
                    />
                    Verify
                  </span>
                )}
              </RippleButton>

              <button
                onClick={handleResendOtp}
                className="w-full text-sm font-medium text-gray-600 hover:text-blue-600 transition-all duration-300 py-2 rounded-xl hover:bg-white/40 hover:shadow-sm"
                disabled={isLoading}
              >
                Didn't receive code?{" "}
                <span className="underline underline-offset-2 decoration-2 decoration-blue-400">
                  Resend
                </span>
              </button>
            </div>
          </div>
        </div>

        {/* Bottom text */}
        <p className="text-center text-sm text-gray-500 mt-6 backdrop-blur-sm bg-white/30 rounded-full px-4 py-2 inline-block w-full">
          Secure registration powered by OTP verification
        </p>
      </div>

      <style>{`
        @keyframes blob {
          0%, 100% {
            transform: translate(0, 0) scale(1);
          }
          33% {
            transform: translate(30px, -50px) scale(1.1);
          }
          66% {
            transform: translate(-20px, 20px) scale(0.9);
          }
        }
        .animate-blob {
          animation: blob 7s infinite;
        }
        .animation-delay-2000 {
          animation-delay: 2s;
        }
        .animation-delay-4000 {
          animation-delay: 4s;
        }
      `}</style>
    </div>
  );
}

export default SignInPage;
