import MinimalHeader from "@/components/local/MinimalHeader";
import { useAppSelector } from "@/store/hooks";
import type { IUser } from "@shared/user.types";
import axiosInstance from "@/utils/axiosConfig";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import {
  type MutableRefObject,
  startTransition,
  useEffect,
  useMemo,
  useRef,
  useState,
  lazy,
  Suspense,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  apiSectionConfigs,
  genderOptions,
  heardAboutOptions,
  interactionOptions,
  languageOptions,
  MIN_GEMINI_API_KEYS,
  MIN_GROQ_API_KEYS,
  sections,
} from "./constants";
import type {
  OnboardingDraft,
  OnboardingLocationState,
  SectionId,
  VoiceCatalogEntry,
  VoiceGender,
} from "./types";
import {
  countFilledTokens,
  ensureMinimumTokenRows,
  normalizeOnboardingLanguage,
  normalizeOnboardingDraft,
  prettifyValue,
  resolveHeardAboutSparkValue,
  trimTokens,
} from "./utils";
import {
  getVoicesForLanguageAndGender,
  loadVoiceCatalog,
} from "./voices/catalog";

// Lazy-load section components
const PreferredNameSection = lazy(() => import("./sections/PreferredNameSection"));
const VoicePreferencesSection = lazy(() => import("./sections/VoicePreferencesSection"));
const HeardAboutSection = lazy(() => import("./sections/HeardAboutSection"));
const SelectionSection = lazy(() => import("./sections/SelectionSection"));
const ApiKeysSection = lazy(() => import("./sections/ApiKeysSection"));
const SummarySection = lazy(() => import("./sections/SummarySection"));

function hasFilledTokens(values: string[]) {
  return values.some((v) => v.trim().length > 0);
}

function isVoiceGender(value: string | undefined): value is VoiceGender {
  return value === "male" || value === "female";
}

function stopAudio(audioRef: MutableRefObject<HTMLAudioElement | null>) {
  const audio = audioRef.current;
  if (!audio) return;
  audio.pause();
  audio.currentTime = 0;
  audioRef.current = null;
}

function resolveName(user: IUser | null | undefined, draft?: Partial<OnboardingDraft>) {
  return draft?.preferredName ?? draft?.fullName ?? user?.fullName ?? user?.username ?? "";
}

function deriveHeardAboutState(source: unknown) {
  const normalized = typeof source === "string" ? source.trim() : "";
  if (!normalized) return { heardAboutSpark: "", heardAboutSparkCustom: "" };

  const aliasMap: Record<string, string> = {
    youtube: "youtube", instagram: "instagram", friend: "friend",
    referral: "friend", twitter: "x-twitter", "x-twitter": "x-twitter",
    x: "x-twitter", linkedin: "linkedin", reddit: "reddit",
    github: "github", discord: "discord", other: "other",
  };
  const matched = aliasMap[normalized.toLowerCase()];
  if (matched) return { heardAboutSpark: matched, heardAboutSparkCustom: "" };
  return { heardAboutSpark: "other", heardAboutSparkCustom: normalized };
}

function buildInitialDraft(incomingDraft: OnboardingDraft | undefined, user: IUser | null | undefined) {
  const resolvedName = resolveName(user, incomingDraft);
  const heardAbout = deriveHeardAboutState(user?.customAttributes?.heard_about_spark);

  return normalizeOnboardingDraft({
    preferredName: resolvedName,
    fullName: resolvedName,
    gender: incomingDraft?.gender ?? user?.gender ?? "",
    heardAboutSpark: incomingDraft?.heardAboutSpark ?? heardAbout.heardAboutSpark,
    heardAboutSparkCustom: incomingDraft?.heardAboutSparkCustom ?? heardAbout.heardAboutSparkCustom,
    interactionStyle: incomingDraft?.interactionStyle ?? user?.behavioralTags?.[0] ?? "",
    language: normalizeOnboardingLanguage(incomingDraft?.language),
    aiGender: isVoiceGender(incomingDraft?.aiGender) ? incomingDraft.aiGender : isVoiceGender(user?.aiGender) ? user.aiGender : "",
    aiVoiceName: incomingDraft?.aiVoiceName ?? user?.aiVoiceName ?? "",
    geminiApiKeys: incomingDraft?.geminiApiKeys ?? ensureMinimumTokenRows(user?.geminiApiKeys),
    groqApiKeys: incomingDraft?.groqApiKeys ?? ensureMinimumTokenRows(user?.groqApiKeys),
    openrouterApiKeys: incomingDraft?.openrouterApiKeys ?? ensureMinimumTokenRows(user?.openrouterApiKeys),
  });
}

function SectionLoader() {
  return <div className="flex items-center justify-center py-12"><div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>;
}

function Onboarding() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAppSelector((state) => state.auth);
  const locationState = (location.state as OnboardingLocationState | null) ?? null;
  const incomingDraft = locationState?.onboardingDraft;
  const shouldResumeAtReview = Boolean(locationState?.resumeAtReview);

  const [currentSectionIndex, setCurrentSectionIndex] = useState(shouldResumeAtReview ? sections.length - 1 : 0);
  const [furthestVisitedIndex, setFurthestVisitedIndex] = useState(shouldResumeAtReview ? sections.length - 1 : 0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [draft, setDraft] = useState<OnboardingDraft>(() => buildInitialDraft(incomingDraft, user));
  const [voiceCatalog, setVoiceCatalog] = useState<VoiceCatalogEntry[]>([]);
  const [isVoiceCatalogLoading, setIsVoiceCatalogLoading] = useState(true);
  const [voiceCatalogError, setVoiceCatalogError] = useState<string | null>(null);
  const [previewingVoiceId, setPreviewingVoiceId] = useState<string | null>(null);
  const [previewVisualizerBars, setPreviewVisualizerBars] = useState<number[]>([]);

  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewAudioContextRef = useRef<AudioContext | null>(null);
  const previewAnalyserRef = useRef<AnalyserNode | null>(null);
  const previewSourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const previewAnimationFrameRef = useRef<number | null>(null);

  const section = sections[currentSectionIndex];
  const hasAuthenticatedSession = Boolean(user?._id);
  const progressPercent = ((currentSectionIndex + 1) / sections.length) * 100;

  const geminiApiKeyCount = useMemo(() => countFilledTokens(draft.geminiApiKeys), [draft.geminiApiKeys]);
  const groqApiKeyCount = useMemo(() => countFilledTokens(draft.groqApiKeys), [draft.groqApiKeys]);

  const maleVoices = useMemo(() => getVoicesForLanguageAndGender(voiceCatalog, draft.language, "male"), [draft.language, voiceCatalog]);
  const femaleVoices = useMemo(() => getVoicesForLanguageAndGender(voiceCatalog, draft.language, "female"), [draft.language, voiceCatalog]);
  const availableVoices = useMemo(() => [...maleVoices, ...femaleVoices], [maleVoices, femaleVoices]);

  // Load voice catalog
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const catalog = await loadVoiceCatalog();
        if (!cancelled) setVoiceCatalog(catalog);
      } catch {
        if (!cancelled) setVoiceCatalogError("Could not load voice catalog.");
      } finally {
        if (!cancelled) setIsVoiceCatalogLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Sync draft with user data
  useEffect(() => {
    if (!user) return;
    const heardAbout = deriveHeardAboutState(user.customAttributes?.heard_about_spark);
    setDraft((d) => normalizeOnboardingDraft({
      ...d,
      preferredName: d.preferredName || resolveName(user, d),
      fullName: d.fullName || resolveName(user, d),
      gender: d.gender || user.gender || "",
      heardAboutSpark: d.heardAboutSpark || heardAbout.heardAboutSpark,
      heardAboutSparkCustom: d.heardAboutSpark === "other" ? d.heardAboutSparkCustom || heardAbout.heardAboutSparkCustom : d.heardAboutSparkCustom,
      interactionStyle: d.interactionStyle || user.behavioralTags?.[0] || "",
      language: normalizeOnboardingLanguage(d.language),
      aiGender: d.aiGender || (isVoiceGender(user.aiGender) ? user.aiGender : ""),
      aiVoiceName: d.aiVoiceName || user.aiVoiceName || "",
      geminiApiKeys: hasFilledTokens(d.geminiApiKeys) ? d.geminiApiKeys : ensureMinimumTokenRows(user.geminiApiKeys),
      groqApiKeys: hasFilledTokens(d.groqApiKeys) ? d.groqApiKeys : ensureMinimumTokenRows(user.groqApiKeys),
      openrouterApiKeys: hasFilledTokens(d.openrouterApiKeys) ? d.openrouterApiKeys : ensureMinimumTokenRows(user.openrouterApiKeys),
    }));
  }, [user]);

  // Voice fallback
  useEffect(() => {
    if (availableVoices.length === 0) return;
    setDraft((d) => {
      if (!d.aiVoiceName) return d;
      const found = availableVoices.find((v) => v.id === d.aiVoiceName);
      if (found) return d.aiGender === found.gender ? d : { ...d, aiGender: found.gender };
      return { ...d, aiVoiceName: availableVoices[0].id, aiGender: availableVoices[0].gender };
    });
  }, [availableVoices]);

  // Cleanup preview on section change
  useEffect(() => {
    if (section.id !== "voicePreferences") stopPreviewPlayback();
  }, [section.id]);

  function clearPreviewVisualizer() {
    if (previewAnimationFrameRef.current !== null) {
      window.cancelAnimationFrame(previewAnimationFrameRef.current);
      previewAnimationFrameRef.current = null;
    }
    previewSourceRef.current?.disconnect();
    previewSourceRef.current = null;
    previewAnalyserRef.current?.disconnect();
    previewAnalyserRef.current = null;
    const ctx = previewAudioContextRef.current;
    previewAudioContextRef.current = null;
    if (ctx && ctx.state !== "closed") void ctx.close().catch(() => {});
    setPreviewVisualizerBars([]);
  }

  function stopPreviewPlayback() {
    stopAudio(previewAudioRef);
    setPreviewingVoiceId(null);
    clearPreviewVisualizer();
  }

  async function startPreviewVisualizer(audio: HTMLAudioElement) {
    clearPreviewVisualizer();
    const AC = window.AudioContext || (window as any).webkitAudioContext;
    if (!AC) return;
    try {
      const ctx = new AC();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.82;
      const source = ctx.createMediaElementSource(audio);
      source.connect(analyser);
      analyser.connect(ctx.destination);
      previewAudioContextRef.current = ctx;
      previewAnalyserRef.current = analyser;
      previewSourceRef.current = source;
      if (ctx.state === "suspended") await ctx.resume();
      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      const render = () => {
        if (!previewAnalyserRef.current) return;
        previewAnalyserRef.current.getByteFrequencyData(dataArray);
        const bars = Array.from({ length: 12 }, (_, i) => {
          const s = Math.floor((i * dataArray.length) / 12);
          const e = Math.floor(((i + 1) * dataArray.length) / 12);
          const avg = dataArray.slice(s, e).reduce((a, b) => a + b, 0) / Math.max(e - s, 1);
          return Math.max(20, Math.round((avg / 255) * 100));
        });
        setPreviewVisualizerBars(bars);
        previewAnimationFrameRef.current = window.requestAnimationFrame(render);
      };
      render();
    } catch { clearPreviewVisualizer(); }
  }

  const moveToSection = (idx: number) => {
    startTransition(() => {
      setCurrentSectionIndex(idx);
      setFurthestVisitedIndex((c) => Math.max(c, idx));
    });
  };

  const updateDraftField = <K extends keyof OnboardingDraft>(key: K, value: OnboardingDraft[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
  };

  const isSectionSatisfied = (id: SectionId) => {
    switch (id) {
      case "preferredName": return Boolean(draft.preferredName.trim());
      case "voicePreferences": return Boolean(draft.aiGender && draft.aiVoiceName);
      case "heardAboutSpark": return Boolean(draft.heardAboutSpark && (draft.heardAboutSpark !== "other" || draft.heardAboutSparkCustom.trim()));
      case "interactionStyle": return Boolean(draft.interactionStyle);
      case "language": return Boolean(draft.language);
      case "geminiKeys": return geminiApiKeyCount >= MIN_GEMINI_API_KEYS;
      case "groqKeys": return groqApiKeyCount >= MIN_GROQ_API_KEYS;
      case "openrouterKeys": return true;
      case "summary": return false;
      default: return false;
    }
  };

  const validateCurrentSection = () => {
    const msgs: Record<string, string> = {
      preferredName: "Enter your name first.",
      voicePreferences: "Pick a voice.",
      heardAboutSpark: "Select where you heard about Spark.",
      interactionStyle: "Choose a response style.",
      language: "Choose a language.",
      geminiKeys: "Add at least one Gemini API key.",
      groqKeys: "Add at least one Groq API key.",
    };
    if (!isSectionSatisfied(section.id) && msgs[section.id]) {
      toast.error(msgs[section.id]);
      return false;
    }
    return true;
  };

  const handleBack = async () => {
    if (currentSectionIndex > 0) { moveToSection(currentSectionIndex - 1); return; }
    if (hasAuthenticatedSession) { await window.electronApi.onAuthSuccess(); navigate("/home", { replace: true }); return; }
    navigate("/welcome");
  };

  const handleNext = () => {
    if (!validateCurrentSection()) return;
    if (currentSectionIndex < sections.length - 1) moveToSection(currentSectionIndex + 1);
  };

  const handlePreviewVoice = async (voice: VoiceCatalogEntry) => {
    if (!voice.audioUrl) return;
    if (previewingVoiceId === voice.id) { stopPreviewPlayback(); return; }
    stopPreviewPlayback();
    const audio = new Audio(voice.audioUrl);
    audio.volume = 0.9;
    previewAudioRef.current = audio;
    setPreviewingVoiceId(voice.id);
    audio.onended = () => stopPreviewPlayback();
    audio.onerror = () => { stopPreviewPlayback(); toast.error("Could not play voice sample."); };
    try { await startPreviewVisualizer(audio); await audio.play(); }
    catch { stopPreviewPlayback(); }
  };

  const handleComplete = async () => {
    if (!draft.preferredName.trim()) { toast.error("Name is missing."); moveToSection(0); return; }
    if (!draft.aiGender || !draft.aiVoiceName) { toast.error("Finish voice selection."); moveToSection(1); return; }
    if (!draft.heardAboutSpark) { toast.error("Finish heard-about section."); return; }
    if (!draft.interactionStyle || !draft.language) { toast.error("Complete all sections."); return; }
    if (geminiApiKeyCount < MIN_GEMINI_API_KEYS) { toast.error("Add Gemini API key."); return; }
    if (groqApiKeyCount < MIN_GROQ_API_KEYS) { toast.error("Add Groq API key."); return; }

    if (!hasAuthenticatedSession || !user?._id) {
      toast.error("Create your account first.");
      navigate("/auth/sign-up", { state: { onboardingDraft: draft } satisfies OnboardingLocationState });
      return;
    }

    setIsSubmitting(true);
    try {
      const heardAboutValue = draft.heardAboutSpark === "other"
        ? draft.heardAboutSparkCustom.trim()
        : resolveHeardAboutSparkValue(draft.heardAboutSpark, draft.heardAboutSparkCustom);

      await axiosInstance.patch(`/auth/update-user-details?userId=${user._id}`, {
        username: draft.preferredName.trim(),
        full_name: draft.fullName.trim(),
        gender: draft.gender,
        language: draft.language,
        ai_gender: draft.aiGender,
        ai_voice_name: draft.aiVoiceName,
        behavioral_tags: draft.interactionStyle ? [draft.interactionStyle] : [],
        api_keys: {
          groq: trimTokens(draft.groqApiKeys),
          gemini: trimTokens(draft.geminiApiKeys),
          openrouter: trimTokens(draft.openrouterApiKeys),
          cerebras: trimTokens(draft.cerebrasApiKeys),
          sambanova: trimTokens(draft.sambanovaApiKeys),
          mistral: trimTokens(draft.mistralApiKeys),
        },
        custom_attributes: {
          ...(user.customAttributes ?? {}),
          heard_about_spark: heardAboutValue,
          onboarding_completed: true,
          onboarding_completed_at: new Date().toISOString(),
        },
      });

      toast.success("Profile saved. Opening Spark.");
      await window.electronApi.onAuthSuccess();
      navigate("/home", { replace: true });
    } catch {
      toast.error("Could not save profile.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const renderSection = () => {
    const fallback = <SectionLoader />;
    switch (section.id) {
      case "preferredName":
        return <Suspense fallback={fallback}><PreferredNameSection eyebrow={section.eyebrow} title={section.title} description={section.description} value={draft.preferredName} gender={draft.gender} genderOptions={genderOptions} onChange={(v) => setDraft((d) => ({ ...d, preferredName: v, fullName: v }))} onGenderChange={(v) => updateDraftField("gender", v)} onSubmit={handleNext} /></Suspense>;
      case "voicePreferences":
        return <Suspense fallback={fallback}><VoicePreferencesSection eyebrow={section.eyebrow} title={section.title} description={section.description} aiVoiceName={draft.aiVoiceName} maleVoices={maleVoices} femaleVoices={femaleVoices} isLoading={isVoiceCatalogLoading} errorMessage={voiceCatalogError} previewingVoiceId={previewingVoiceId} previewVisualizerBars={previewVisualizerBars} onVoiceChange={(v) => setDraft((d) => ({ ...d, aiGender: v.gender, aiVoiceName: v.id }))} onPreviewVoice={(v) => void handlePreviewVoice(v)} /></Suspense>;
      case "heardAboutSpark":
        return <Suspense fallback={fallback}><HeardAboutSection eyebrow={section.eyebrow} title={section.title} description={section.description} options={heardAboutOptions} value={draft.heardAboutSpark} customValue={draft.heardAboutSparkCustom} onChange={(v) => { updateDraftField("heardAboutSpark", v); if (v !== "other") updateDraftField("heardAboutSparkCustom", ""); }} onCustomValueChange={(v) => updateDraftField("heardAboutSparkCustom", v)} /></Suspense>;
      case "interactionStyle":
        return <Suspense fallback={fallback}><SelectionSection eyebrow={section.eyebrow} title={section.title} description={section.description} options={interactionOptions} value={draft.interactionStyle} columns="three" onChange={(v) => updateDraftField("interactionStyle", v)} /></Suspense>;
      case "language":
        return <Suspense fallback={fallback}><SelectionSection eyebrow={section.eyebrow} title={section.title} description={section.description} options={languageOptions} value={draft.language} columns="three" onChange={(v) => updateDraftField("language", v)} /></Suspense>;
      case "geminiKeys":
        return <Suspense fallback={fallback}><ApiKeysSection eyebrow={section.eyebrow} title={section.title} description={section.description} config={apiSectionConfigs.gemini} values={draft.geminiApiKeys} onChange={(v) => updateDraftField("geminiApiKeys", v)} /></Suspense>;
      case "groqKeys":
        return <Suspense fallback={fallback}><ApiKeysSection eyebrow={section.eyebrow} title={section.title} description={section.description} config={apiSectionConfigs.groq} values={draft.groqApiKeys} onChange={(v) => updateDraftField("groqApiKeys", v)} /></Suspense>;
      case "openrouterKeys":
        return <Suspense fallback={fallback}><ApiKeysSection eyebrow={section.eyebrow} title={section.title} description={section.description} config={apiSectionConfigs.openrouter} values={draft.openrouterApiKeys} onChange={(v) => updateDraftField("openrouterApiKeys", v)} /></Suspense>;
      case "cerebrasKeys":
        return <Suspense fallback={fallback}><ApiKeysSection eyebrow={section.eyebrow} title={section.title} description={section.description} config={apiSectionConfigs.cerebras} values={draft.cerebrasApiKeys} onChange={(v) => updateDraftField("cerebrasApiKeys", v)} /></Suspense>;
      case "sambanovaKeys":
        return <Suspense fallback={fallback}><ApiKeysSection eyebrow={section.eyebrow} title={section.title} description={section.description} config={apiSectionConfigs.sambanova} values={draft.sambanovaApiKeys} onChange={(v) => updateDraftField("sambanovaApiKeys", v)} /></Suspense>;
      case "mistralKeys":
        return <Suspense fallback={fallback}><ApiKeysSection eyebrow={section.eyebrow} title={section.title} description={section.description} config={apiSectionConfigs.mistral} values={draft.mistralApiKeys} onChange={(v) => updateDraftField("mistralApiKeys", v)} /></Suspense>;
      case "summary":
        return <Suspense fallback={fallback}><SummarySection eyebrow={section.eyebrow} title={section.title} description={section.description} draft={draft} voiceDisplayName={availableVoices.find((v) => v.id === draft.aiVoiceName)?.name} /></Suspense>;
      default: return null;
    }
  };

  return (
    <div className="h-screen w-screen bg-[#0a0a0f] text-white select-none flex flex-col overflow-hidden">
      <MinimalHeader />

      {/* Progress bar */}
      <div className="px-6 pt-2">
        <div className="flex items-center justify-between text-[11px] text-slate-500 mb-1.5">
          <span>{section.eyebrow}</span>
          <span>{currentSectionIndex + 1} / {sections.length}</span>
        </div>
        <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-blue-500 rounded-full transition-all duration-300" style={{ width: `${progressPercent}%` }} />
        </div>
      </div>

      {/* Section nav dots */}
      <div className="flex items-center justify-center gap-2 py-4">
        {sections.map((s, i) => (
          <button
            key={s.id}
            onClick={() => i <= furthestVisitedIndex && moveToSection(i)}
            disabled={i > furthestVisitedIndex}
            className={`w-2.5 h-2.5 rounded-full transition-all ${
              i === currentSectionIndex
                ? "bg-blue-500 scale-125"
                : i < furthestVisitedIndex && isSectionSatisfied(s.id)
                  ? "bg-green-500/60"
                  : i <= furthestVisitedIndex
                    ? "bg-slate-600 hover:bg-slate-500"
                    : "bg-slate-800"
            }`}
            title={s.title}
          />
        ))}
      </div>

      {/* Section content */}
      <div className="flex-1 overflow-y-auto px-6 pb-4">
        <div className="w-[80%] mx-auto">
          {renderSection()}
        </div>
      </div>

      {/* Navigation buttons */}
      <div className="px-6 py-4 border-t border-slate-800 flex items-center justify-between">
        <button
          onClick={() => void handleBack()}
          disabled={isSubmitting}
          className="flex items-center gap-2 px-4 py-2.5 text-sm text-slate-400 hover:text-white border border-slate-700 hover:border-slate-600 rounded-lg transition-colors disabled:opacity-50"
        >
          <ArrowLeft size={14} />
          {currentSectionIndex === 0 ? (hasAuthenticatedSession ? "Skip" : "Back") : "Previous"}
        </button>

        {section.id === "summary" ? (
          <button
            onClick={() => void handleComplete()}
            disabled={isSubmitting}
            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
          >
            {isSubmitting ? "Saving..." : hasAuthenticatedSession ? "Save & Launch" : "Create Account"}
          </button>
        ) : (
          <button
            onClick={handleNext}
            disabled={isSubmitting}
            className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
          >
            Next <ArrowRight size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

export default Onboarding;
