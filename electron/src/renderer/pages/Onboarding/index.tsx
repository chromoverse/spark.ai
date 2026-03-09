import MinimalHeader from "@/components/local/MinimalHeader";
import LiquidGradientBackground from "@/components/local/LiquidGradientBackground";
import { RippleButton } from "@/components/ui/ripple-button";
import { useAppSelector } from "@/store/hooks";
import type { IUser } from "@shared/user.types";
import axiosInstance from "@/utils/axiosConfig";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Menu,
  Sparkles,
  Volume2,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  type MutableRefObject,
  type MouseEvent as ReactMouseEvent,
  startTransition,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import SummaryCard from "./components/SummaryCard";
import {
  apiSectionConfigs,
  genderOptions,
  heardAboutOptions,
  interactionOptions,
  languageOptions,
  MIN_GEMINI_API_KEYS,
  MIN_GROQ_API_KEYS,
  sections,
  sectionVariants,
} from "./constants";
import ApiKeysSection from "./sections/ApiKeysSection";
import HeardAboutSection from "./sections/HeardAboutSection";
import PreferredNameSection from "./sections/PreferredNameSection";
import SelectionSection from "./sections/SelectionSection";
import SummarySection from "./sections/SummarySection";
import VoicePreferencesSection from "./sections/VoicePreferencesSection";
import type {
  OnboardingDraft,
  OnboardingLocationState,
  OnboardingPhase,
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
  onboardingIntroAudioUrl,
} from "./voices/catalog";

function hasFilledTokens(values: string[]) {
  return values.some((value) => value.trim().length > 0);
}

function isVoiceGender(value: string | undefined): value is VoiceGender {
  return value === "male" || value === "female";
}

function stopAudio(audioRef: MutableRefObject<HTMLAudioElement | null>) {
  const audio = audioRef.current;
  if (!audio) {
    return;
  }

  audio.pause();
  audio.currentTime = 0;
  audioRef.current = null;
}

function resolveName(user: IUser | null | undefined, draft?: Partial<OnboardingDraft>) {
  return (
    draft?.preferredName ??
    draft?.fullName ??
    user?.fullName ??
    user?.username ??
    ""
  );
}

function deriveHeardAboutState(source: unknown) {
  const normalized = typeof source === "string" ? source.trim() : "";
  if (!normalized) {
    return {
      heardAboutSpark: "",
      heardAboutSparkCustom: "",
    };
  }

  const normalizedKey = normalized.toLowerCase();
  const aliasMap: Record<string, string> = {
    youtube: "youtube",
    instagram: "instagram",
    friend: "friend",
    referral: "friend",
    "friend or referral": "friend",
    twitter: "x-twitter",
    "x / twitter": "x-twitter",
    "x-twitter": "x-twitter",
    x: "x-twitter",
    linkedin: "linkedin",
    reddit: "reddit",
    github: "github",
    discord: "discord",
    other: "other",
  };
  const matchedValue = aliasMap[normalizedKey];
  const matchingOption = heardAboutOptions.find(
    (option) => option.value === matchedValue,
  );

  if (matchingOption) {
    return {
      heardAboutSpark: matchingOption.value,
      heardAboutSparkCustom: "",
    };
  }

  return {
    heardAboutSpark: "other",
    heardAboutSparkCustom: normalized,
  };
}

function buildInitialDraft(
  incomingDraft: OnboardingDraft | undefined,
  user: IUser | null | undefined,
) {
  const initialAiGender = isVoiceGender(user?.aiGender)
    ? user.aiGender
    : incomingDraft?.aiGender;
  const resolvedName = resolveName(user, incomingDraft);
  const heardAboutFromUser = deriveHeardAboutState(
    user?.customAttributes?.heard_about_spark,
  );

  return normalizeOnboardingDraft({
    preferredName: resolvedName,
    fullName: resolvedName,
    gender: incomingDraft?.gender ?? user?.gender ?? "",
    heardAboutSpark:
      incomingDraft?.heardAboutSpark ?? heardAboutFromUser.heardAboutSpark,
    heardAboutSparkCustom:
      incomingDraft?.heardAboutSparkCustom ??
      heardAboutFromUser.heardAboutSparkCustom,
    interactionStyle:
      incomingDraft?.interactionStyle ?? user?.behavioralTags?.[0] ?? "",
    language: normalizeOnboardingLanguage(incomingDraft?.language),
    aiGender: isVoiceGender(initialAiGender) ? initialAiGender : "",
    aiVoiceName: incomingDraft?.aiVoiceName ?? user?.aiVoiceName ?? "",
    geminiApiKeys:
      incomingDraft?.geminiApiKeys ?? ensureMinimumTokenRows(user?.geminiApiKeys),
    groqApiKeys:
      incomingDraft?.groqApiKeys ?? ensureMinimumTokenRows(user?.groqApiKeys),
    openrouterApiKeys:
      incomingDraft?.openrouterApiKeys ??
      ensureMinimumTokenRows(user?.openrouterApiKeys),
  });
}

function Onboarding() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAppSelector((state) => state.auth);
  const locationState = (location.state as OnboardingLocationState | null) ?? null;
  const incomingDraft = locationState?.onboardingDraft;
  const shouldSkipIntro = Boolean(locationState?.skipIntro);
  const shouldResumeAtReview = Boolean(locationState?.resumeAtReview);

  const [phase, setPhase] = useState<OnboardingPhase>(
    shouldSkipIntro ? "form" : "intro",
  );
  const [showIntroCopy, setShowIntroCopy] = useState(false);
  const [direction, setDirection] = useState(1);
  const [currentSectionIndex, setCurrentSectionIndex] = useState(
    shouldResumeAtReview ? sections.length - 1 : 0,
  );
  const [furthestVisitedIndex, setFurthestVisitedIndex] = useState(
    shouldResumeAtReview ? sections.length - 1 : 0,
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [draft, setDraft] = useState<OnboardingDraft>(() =>
    buildInitialDraft(incomingDraft, user),
  );
  const [voiceCatalog, setVoiceCatalog] = useState<VoiceCatalogEntry[]>([]);
  const [isVoiceCatalogLoading, setIsVoiceCatalogLoading] = useState(true);
  const [voiceCatalogError, setVoiceCatalogError] = useState<string | null>(null);
  const [previewingVoiceId, setPreviewingVoiceId] = useState<string | null>(null);
  const [previewVisualizerBars, setPreviewVisualizerBars] = useState<number[]>([]);
  const [isSidebarPinned, setIsSidebarPinned] = useState(false);
  const [isSidebarHovering, setIsSidebarHovering] = useState(false);
  const [isSidebarNearEdge, setIsSidebarNearEdge] = useState(false);

  const introAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewAudioContextRef = useRef<AudioContext | null>(null);
  const previewAnalyserRef = useRef<AnalyserNode | null>(null);
  const previewSourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const previewAnimationFrameRef = useRef<number | null>(null);

  const section = sections[currentSectionIndex];
  const isSummarySection = section.id === "summary";
  const isSidebarOpen =
    !isSummarySection && (isSidebarPinned || isSidebarHovering || isSidebarNearEdge);
  const hasAuthenticatedSession = Boolean(user?._id);
  const progressValue = ((currentSectionIndex + 1) / sections.length) * 100;

  const maleVoices = useMemo(
    () =>
      getVoicesForLanguageAndGender(voiceCatalog, draft.language, "male"),
    [draft.language, voiceCatalog],
  );

  const femaleVoices = useMemo(
    () =>
      getVoicesForLanguageAndGender(voiceCatalog, draft.language, "female"),
    [draft.language, voiceCatalog],
  );

  const availableVoices = useMemo(
    () => [...maleVoices, ...femaleVoices],
    [femaleVoices, maleVoices],
  );

  const selectedHeardAboutLabel = useMemo(
    () =>
      resolveHeardAboutSparkValue(
        draft.heardAboutSpark,
        draft.heardAboutSparkCustom,
      ),
    [draft.heardAboutSpark, draft.heardAboutSparkCustom],
  );

  const selectedLanguageLabel = useMemo(
    () => languageOptions.find((option) => option.value === draft.language)?.label,
    [draft.language],
  );

  const selectedVoiceDisplayName = useMemo(
    () => availableVoices.find((voice) => voice.id === draft.aiVoiceName)?.name,
    [availableVoices, draft.aiVoiceName],
  );

  const totalApiKeys = useMemo(
    () =>
      countFilledTokens(draft.geminiApiKeys) +
      countFilledTokens(draft.groqApiKeys) +
      countFilledTokens(draft.openrouterApiKeys),
    [draft.geminiApiKeys, draft.groqApiKeys, draft.openrouterApiKeys],
  );
  const geminiApiKeyCount = useMemo(
    () => countFilledTokens(draft.geminiApiKeys),
    [draft.geminiApiKeys],
  );
  const groqApiKeyCount = useMemo(
    () => countFilledTokens(draft.groqApiKeys),
    [draft.groqApiKeys],
  );

  useEffect(() => {
    let isCancelled = false;

    const loadCatalog = async () => {
      setIsVoiceCatalogLoading(true);
      setVoiceCatalogError(null);

      try {
        const catalog = await loadVoiceCatalog();
        if (isCancelled) {
          return;
        }
        setVoiceCatalog(catalog);
      } catch (error) {
        console.error("Failed to load onboarding voice catalog", error);
        if (isCancelled) {
          return;
        }
        setVoiceCatalogError("Spark could not load the voice catalog.");
      } finally {
        if (!isCancelled) {
          setIsVoiceCatalogLoading(false);
        }
      }
    };

    void loadCatalog();

    return () => {
      isCancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!user) {
      return;
    }

    const heardAboutFromUser = deriveHeardAboutState(
      user.customAttributes?.heard_about_spark,
    );

    setDraft((currentDraft) => {
        const nextHeardAboutSpark =
          currentDraft.heardAboutSpark || heardAboutFromUser.heardAboutSpark;
        const resolvedName = resolveName(user, currentDraft);

        return normalizeOnboardingDraft({
          ...currentDraft,
          preferredName: currentDraft.preferredName || resolvedName,
          fullName: currentDraft.fullName || resolvedName,
          gender: currentDraft.gender || user.gender || "",
          heardAboutSpark: nextHeardAboutSpark,
          heardAboutSparkCustom:
            nextHeardAboutSpark === "other"
              ? currentDraft.heardAboutSparkCustom ||
                heardAboutFromUser.heardAboutSparkCustom
              : currentDraft.heardAboutSparkCustom,
          interactionStyle:
            currentDraft.interactionStyle || user.behavioralTags?.[0] || "",
          language: normalizeOnboardingLanguage(currentDraft.language),
          aiGender:
            currentDraft.aiGender ||
            (isVoiceGender(user.aiGender) ? user.aiGender : ""),
          aiVoiceName: currentDraft.aiVoiceName || user.aiVoiceName || "",
          geminiApiKeys: hasFilledTokens(currentDraft.geminiApiKeys)
            ? currentDraft.geminiApiKeys
            : ensureMinimumTokenRows(user.geminiApiKeys),
          groqApiKeys: hasFilledTokens(currentDraft.groqApiKeys)
            ? currentDraft.groqApiKeys
            : ensureMinimumTokenRows(user.groqApiKeys),
          openrouterApiKeys: hasFilledTokens(currentDraft.openrouterApiKeys)
            ? currentDraft.openrouterApiKeys
            : ensureMinimumTokenRows(user.openrouterApiKeys),
        });
    });
  }, [user]);

  useEffect(() => {
    setDraft((currentDraft) => {
      if (availableVoices.length === 0) {
        if (!currentDraft.aiVoiceName && !currentDraft.aiGender) {
          return currentDraft;
        }

        return {
          ...currentDraft,
          aiVoiceName: "",
          aiGender: "",
        };
      }

      if (!currentDraft.aiVoiceName) {
        return currentDraft;
      }

      const selectedVoice = availableVoices.find(
        (voice) => voice.id === currentDraft.aiVoiceName,
      );
      if (selectedVoice) {
        if (currentDraft.aiGender === selectedVoice.gender) {
          return currentDraft;
        }

        return {
          ...currentDraft,
          aiGender: selectedVoice.gender,
        };
      }

      const fallbackVoice = availableVoices[0];
      if (!fallbackVoice) {
        return currentDraft;
      }

      return {
        ...currentDraft,
        aiVoiceName: fallbackVoice.id,
        aiGender: fallbackVoice.gender,
      };
    });
  }, [availableVoices]);

  useEffect(() => {
    if (isSummarySection) {
      setIsSidebarHovering(false);
      setIsSidebarNearEdge(false);
    }
  }, [isSummarySection]);

  useEffect(() => {
    const timers: number[] = [];
    const cleanupPreview = () => {
      stopAudio(previewAudioRef);
      setPreviewingVoiceId(null);
      if (previewAnimationFrameRef.current !== null) {
        window.cancelAnimationFrame(previewAnimationFrameRef.current);
        previewAnimationFrameRef.current = null;
      }
      previewSourceRef.current?.disconnect();
      previewSourceRef.current = null;
      previewAnalyserRef.current?.disconnect();
      previewAnalyserRef.current = null;

      const audioContext = previewAudioContextRef.current;
      previewAudioContextRef.current = null;
      if (audioContext && audioContext.state !== "closed") {
        void audioContext.close().catch((error) => {
          console.error("Failed to close onboarding preview audio context", error);
        });
      }

      setPreviewVisualizerBars([]);
    };

    const setWindowMode = async (
      mode: "IMMERSIVE" | "MAXIMIZED" | "DEFAULT",
    ) => {
      try {
        await window.electronApi.setOnboardingWindowMode(mode);
      } catch (error) {
        console.error(`Failed to switch onboarding window mode to ${mode}`, error);
      }
    };

    const startIntroAudio = async () => {
      stopAudio(introAudioRef);
      const audio = new Audio(onboardingIntroAudioUrl);
      audio.loop = true;
      audio.volume = 0.18;
      audio.preload = "auto";
      introAudioRef.current = audio;

      try {
        await audio.play();
      } catch (error) {
        console.error("Failed to auto-play onboarding intro audio", error);
      }
    };

    if (shouldSkipIntro) {
      setShowIntroCopy(false);
      setPhase("form");
      void setWindowMode("MAXIMIZED");

      return () => {
        stopAudio(introAudioRef);
        cleanupPreview();
        void setWindowMode("DEFAULT");
      };
    }

    void setWindowMode("IMMERSIVE");
    void startIntroAudio();

    timers.push(window.setTimeout(() => setShowIntroCopy(true), 520));
    timers.push(window.setTimeout(() => void setWindowMode("MAXIMIZED"), 3600));
    timers.push(window.setTimeout(() => setPhase("form"), 4200));

    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
      stopAudio(introAudioRef);
      cleanupPreview();
      void setWindowMode("DEFAULT");
    };
  }, [shouldSkipIntro]);

  useEffect(() => {
    if (phase === "form") {
      stopAudio(introAudioRef);
    }
  }, [phase]);

  useEffect(() => {
    if (section.id !== "voicePreferences") {
      stopAudio(previewAudioRef);
      setPreviewingVoiceId(null);
      if (previewAnimationFrameRef.current !== null) {
        window.cancelAnimationFrame(previewAnimationFrameRef.current);
        previewAnimationFrameRef.current = null;
      }
      previewSourceRef.current?.disconnect();
      previewSourceRef.current = null;
      previewAnalyserRef.current?.disconnect();
      previewAnalyserRef.current = null;

      const audioContext = previewAudioContextRef.current;
      previewAudioContextRef.current = null;
      if (audioContext && audioContext.state !== "closed") {
        void audioContext.close().catch((error) => {
          console.error("Failed to close onboarding preview audio context", error);
        });
      }

      setPreviewVisualizerBars([]);
    }
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

    const audioContext = previewAudioContextRef.current;
    previewAudioContextRef.current = null;
    if (audioContext && audioContext.state !== "closed") {
      void audioContext.close().catch((error) => {
        console.error("Failed to close onboarding preview audio context", error);
      });
    }

    setPreviewVisualizerBars([]);
  }

  function stopPreviewPlayback() {
    stopAudio(previewAudioRef);
    setPreviewingVoiceId(null);
    clearPreviewVisualizer();
  }

  async function startPreviewVisualizer(audio: HTMLAudioElement) {
    clearPreviewVisualizer();

    const AudioContextClass =
      window.AudioContext ||
      (
        window as typeof window & {
          webkitAudioContext?: typeof AudioContext;
        }
      ).webkitAudioContext;

    if (!AudioContextClass) {
      return;
    }

    try {
      const audioContext = new AudioContextClass();
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.82;

      const source = audioContext.createMediaElementSource(audio);
      source.connect(analyser);
      analyser.connect(audioContext.destination);

      previewAudioContextRef.current = audioContext;
      previewAnalyserRef.current = analyser;
      previewSourceRef.current = source;
      setPreviewVisualizerBars(Array.from({ length: 12 }, () => 24));

      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }

      const dataArray = new Uint8Array(analyser.frequencyBinCount);

      const renderFrame = () => {
        if (!previewAnalyserRef.current || previewAudioRef.current !== audio) {
          return;
        }

        previewAnalyserRef.current.getByteFrequencyData(dataArray);
        const nextBars = Array.from({ length: 12 }, (_, index) => {
          const start = Math.floor((index * dataArray.length) / 12);
          const end = Math.floor(((index + 1) * dataArray.length) / 12);
          const slice = dataArray.slice(start, end);
          const average =
            slice.reduce((total, value) => total + value, 0) /
            Math.max(slice.length, 1);

          return Math.max(20, Math.round((average / 255) * 100));
        });

        setPreviewVisualizerBars(nextBars);
        previewAnimationFrameRef.current = window.requestAnimationFrame(renderFrame);
      };

      renderFrame();
    } catch (error) {
      console.error("Failed to start onboarding preview visualizer", error);
      clearPreviewVisualizer();
    }
  }

  const moveToSection = (nextIndex: number) => {
    startTransition(() => {
      setDirection(nextIndex > currentSectionIndex ? 1 : -1);
      setCurrentSectionIndex(nextIndex);
      setFurthestVisitedIndex((currentValue) =>
        nextIndex > currentValue ? nextIndex : currentValue,
      );
    });
  };

  const handleSidebarToggle = () => {
    const nextPinned = !isSidebarPinned;
    setIsSidebarPinned(nextPinned);
    setIsSidebarHovering(nextPinned);
    setIsSidebarNearEdge(false);
  };

  const handleShellMouseMove = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (isSummarySection || isSidebarPinned) {
      return;
    }

    const rect = event.currentTarget.getBoundingClientRect();
    const nearEdge = event.clientX - rect.left <= 36;
    setIsSidebarNearEdge((currentValue) =>
      currentValue === nearEdge ? currentValue : nearEdge,
    );
  };

  const handleShellMouseLeave = () => {
    if (isSidebarPinned) {
      return;
    }

    setIsSidebarNearEdge(false);
    setIsSidebarHovering(false);
  };

  const updateDraftField = <K extends keyof OnboardingDraft>(
    key: K,
    value: OnboardingDraft[K],
  ) => {
    setDraft((currentDraft) => ({
      ...currentDraft,
      [key]: value,
    }));
  };

  const updateName = (value: string) => {
    setDraft((currentDraft) => ({
      ...currentDraft,
      preferredName: value,
      fullName: value,
    }));
  };

  const isSectionSatisfied = (sectionId: SectionId) => {
    switch (sectionId) {
      case "preferredName":
        return Boolean(draft.preferredName.trim());
      case "voicePreferences":
        return Boolean(draft.aiGender && draft.aiVoiceName);
      case "heardAboutSpark":
        return Boolean(
          draft.heardAboutSpark &&
            (draft.heardAboutSpark !== "other" ||
              draft.heardAboutSparkCustom.trim()),
        );
      case "interactionStyle":
        return Boolean(draft.interactionStyle);
      case "language":
        return Boolean(draft.language);
      case "geminiKeys":
        return geminiApiKeyCount >= MIN_GEMINI_API_KEYS;
      case "groqKeys":
        return groqApiKeyCount >= MIN_GROQ_API_KEYS;
      case "openrouterKeys":
        return true;
      case "summary":
        return false;
      default:
        return false;
    }
  };

  const sectionProgress = sections.map((item, index) => {
    const completed = index < furthestVisitedIndex && isSectionSatisfied(item.id);
    const unlocked = index <= furthestVisitedIndex;

    return {
      ...item,
      index,
      completed,
      unlocked,
      isCurrent: index === currentSectionIndex,
    };
  });

  const validateCurrentSection = () => {
    switch (section.id) {
      case "preferredName":
        if (!draft.preferredName.trim()) {
          toast.error("Tell Spark what to call you first.");
          return false;
        }
        return true;
      case "voicePreferences":
        if (!draft.aiGender) {
          toast.error("Choose whether Spark should use a male or female voice.");
          return false;
        }
        if (!draft.aiVoiceName) {
          toast.error("Pick one voice before moving ahead.");
          return false;
        }
        return true;
      case "heardAboutSpark":
        if (!draft.heardAboutSpark) {
          toast.error("Choose where you heard about Spark before moving ahead.");
          return false;
        }
        if (
          draft.heardAboutSpark === "other" &&
          !draft.heardAboutSparkCustom.trim()
        ) {
          toast.error("Type the exact source where you heard about Spark.");
          return false;
        }
        return true;
      case "interactionStyle":
        if (!draft.interactionStyle) {
          toast.error("Choose the response style you want from Spark.");
          return false;
        }
        return true;
      case "language":
        if (!draft.language) {
          toast.error("Choose a language before moving ahead.");
          return false;
        }
        return true;
      case "geminiKeys":
        if (geminiApiKeyCount < MIN_GEMINI_API_KEYS) {
          toast.error("Add at least one Gemini API key before continuing.");
          return false;
        }
        return true;
      case "groqKeys":
        if (groqApiKeyCount < MIN_GROQ_API_KEYS) {
          toast.error("Add at least one Groq API key before continuing.");
          return false;
        }
        return true;
      default:
        return true;
    }
  };

  const handleBack = async () => {
    if (currentSectionIndex > 0) {
      moveToSection(currentSectionIndex - 1);
      return;
    }

    if (hasAuthenticatedSession) {
      await window.electronApi.onAuthSuccess();
      navigate("/home", { replace: true });
      return;
    }

    navigate("/welcome");
  };

  const handleNext = () => {
    if (!validateCurrentSection()) {
      return;
    }

    if (currentSectionIndex < sections.length - 1) {
      moveToSection(currentSectionIndex + 1);
    }
  };

  const handlePreviewVoice = async (voice: VoiceCatalogEntry) => {
    if (!voice.audioUrl) {
      return;
    }

    if (previewingVoiceId === voice.id) {
      stopPreviewPlayback();
      return;
    }

    stopPreviewPlayback();
    const previewAudio = new Audio(voice.audioUrl);
    previewAudio.volume = 0.9;
    previewAudio.preload = "auto";
    previewAudioRef.current = previewAudio;
    setPreviewingVoiceId(voice.id);
    setPreviewVisualizerBars(Array.from({ length: 12 }, () => 22));

    previewAudio.onended = () => {
      stopPreviewPlayback();
    };
    previewAudio.onerror = () => {
      stopPreviewPlayback();
      toast.error("Spark could not play the voice sample.");
    };

    try {
      await startPreviewVisualizer(previewAudio);
      await previewAudio.play();
    } catch (error) {
      console.error("Failed to preview onboarding voice sample", error);
      stopPreviewPlayback();
      toast.error("Spark could not play the voice sample.");
    }
  };

  const handleComplete = async () => {
    if (!draft.preferredName.trim()) {
      toast.error("Your preferred name is still missing.");
      moveToSection(0);
      return;
    }

    if (!draft.aiGender || !draft.aiVoiceName) {
      toast.error("Finish the voice selection before activation.");
      moveToSection(1);
      return;
    }

    if (
      !draft.heardAboutSpark ||
      (draft.heardAboutSpark === "other" && !draft.heardAboutSparkCustom.trim())
    ) {
      toast.error("Finish the heard-about section before activation.");
      moveToSection(sections.findIndex((item) => item.id === "heardAboutSpark"));
      return;
    }

    if (!draft.interactionStyle || !draft.language) {
      toast.error("Finish the remaining sections before activation.");
      return;
    }

    if (geminiApiKeyCount < MIN_GEMINI_API_KEYS) {
      toast.error("Add at least one Gemini API key before activation.");
      moveToSection(sections.findIndex((item) => item.id === "geminiKeys"));
      return;
    }

    if (groqApiKeyCount < MIN_GROQ_API_KEYS) {
      toast.error("Add at least one Groq API key before activation.");
      moveToSection(sections.findIndex((item) => item.id === "groqKeys"));
      return;
    }

    if (!hasAuthenticatedSession || !user?._id) {
      toast.error("Create your account first so Spark can sync this profile.");
      navigate("/auth/sign-up", {
        state: {
          onboardingDraft: draft,
        } satisfies OnboardingLocationState,
      });
      return;
    }

    setIsSubmitting(true);

    try {
      const heardAboutSparkValue =
        draft.heardAboutSpark === "other"
          ? draft.heardAboutSparkCustom.trim()
          : resolveHeardAboutSparkValue(
              draft.heardAboutSpark,
              draft.heardAboutSparkCustom,
            );

      await axiosInstance.patch(`/auth/update-user-details?userId=${user._id}`, {
        username: draft.preferredName.trim(),
        full_name: draft.fullName.trim(),
        gender: draft.gender,
        language: draft.language,
        ai_gender: draft.aiGender,
        ai_voice_name: draft.aiVoiceName,
        behavioral_tags: draft.interactionStyle ? [draft.interactionStyle] : [],
        gemini_api_keys: trimTokens(draft.geminiApiKeys),
        groq_api_keys: trimTokens(draft.groqApiKeys),
        openrouter_api_keys: trimTokens(draft.openrouterApiKeys),
        custom_attributes: {
          ...(user.customAttributes ?? {}),
          heard_about_spark: heardAboutSparkValue,
          onboarding_completed: true,
          onboarding_completed_at: new Date().toISOString(),
          selected_intro: "selected-by-ai",
        },
      });

      toast.success("Onboarding saved. Opening Spark.");
      await window.electronApi.onAuthSuccess();
      navigate("/home", { replace: true });
    } catch (error) {
      console.error("Failed to save onboarding details", error);
      toast.error("Spark could not save your onboarding profile.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const renderSectionBody = () => {
    switch (section.id) {
      case "preferredName":
        return (
          <PreferredNameSection
            eyebrow={section.eyebrow}
            title={section.title}
            description={section.description}
            value={draft.preferredName}
            gender={draft.gender}
            genderOptions={genderOptions}
            onChange={updateName}
            onGenderChange={(value) => updateDraftField("gender", value)}
            onSubmit={handleNext}
          />
        );
      case "voicePreferences":
        return (
          <VoicePreferencesSection
            eyebrow={section.eyebrow}
            title={section.title}
            description={section.description}
            aiVoiceName={draft.aiVoiceName}
            maleVoices={maleVoices}
            femaleVoices={femaleVoices}
            isLoading={isVoiceCatalogLoading}
            errorMessage={voiceCatalogError}
            previewingVoiceId={previewingVoiceId}
            previewVisualizerBars={previewVisualizerBars}
            onVoiceChange={(voice) =>
              setDraft((currentDraft) => ({
                ...currentDraft,
                aiGender: voice.gender,
                aiVoiceName: voice.id,
              }))
            }
            onPreviewVoice={(voice) => void handlePreviewVoice(voice)}
          />
        );
      case "heardAboutSpark":
        return (
          <HeardAboutSection
            eyebrow={section.eyebrow}
            title={section.title}
            description={section.description}
            options={heardAboutOptions}
            value={draft.heardAboutSpark}
            customValue={draft.heardAboutSparkCustom}
            onChange={(value) => {
              updateDraftField("heardAboutSpark", value);
              if (value !== "other") {
                updateDraftField("heardAboutSparkCustom", "");
              }
            }}
            onCustomValueChange={(value) =>
              updateDraftField("heardAboutSparkCustom", value)
            }
          />
        );
      case "interactionStyle":
        return (
          <SelectionSection
            eyebrow={section.eyebrow}
            title={section.title}
            description={section.description}
            options={interactionOptions}
            value={draft.interactionStyle}
            columns="three"
            onChange={(value) => updateDraftField("interactionStyle", value)}
          />
        );
      case "language":
        return (
          <SelectionSection
            eyebrow={section.eyebrow}
            title={section.title}
            description={section.description}
            options={languageOptions}
            value={draft.language}
            columns="three"
            onChange={(value) => updateDraftField("language", value)}
          />
        );
      case "geminiKeys":
        return (
          <ApiKeysSection
            eyebrow={section.eyebrow}
            title={section.title}
            description={section.description}
            config={apiSectionConfigs.gemini}
            values={draft.geminiApiKeys}
            onChange={(values) => updateDraftField("geminiApiKeys", values)}
          />
        );
      case "groqKeys":
        return (
          <ApiKeysSection
            eyebrow={section.eyebrow}
            title={section.title}
            description={section.description}
            config={apiSectionConfigs.groq}
            values={draft.groqApiKeys}
            onChange={(values) => updateDraftField("groqApiKeys", values)}
          />
        );
      case "openrouterKeys":
        return (
          <ApiKeysSection
            eyebrow={section.eyebrow}
            title={section.title}
            description={section.description}
            config={apiSectionConfigs.openrouter}
            values={draft.openrouterApiKeys}
            onChange={(values) =>
              updateDraftField("openrouterApiKeys", values)
            }
          />
        );
      case "summary":
        return (
          <SummarySection
            eyebrow={section.eyebrow}
            title={section.title}
            description={section.description}
            draft={draft}
            voiceDisplayName={selectedVoiceDisplayName}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#060817] text-white select-none">
      <LiquidGradientBackground />

      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.18),transparent_24%),radial-gradient(circle_at_bottom_right,rgba(255,255,255,0.08),transparent_28%)]" />

      <AnimatePresence>
        {phase === "intro" ? (
          <motion.div
            key="intro-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.5 }}
            className="absolute inset-0 z-30 flex items-center justify-center bg-[#040610]/84 backdrop-blur-md"
          >
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(34,211,238,0.18),transparent_32%)]" />

            <div className="relative flex max-w-4xl flex-col items-center px-6 text-center">
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{
                  opacity: showIntroCopy ? 1 : 0,
                  scale: showIntroCopy ? 1 : 0.95,
                }}
                transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                className="mb-6 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/8 px-4 py-2 text-[11px] uppercase tracking-[0.34em] text-slate-200"
              >
                <Volume2 size={14} />
                Selection Protocol
              </motion.div>

              <motion.h1
                initial={{ opacity: 0, y: 92 }}
                animate={{
                  opacity: showIntroCopy ? 1 : 0,
                  y: showIntroCopy ? 0 : 92,
                }}
                transition={{ duration: 0.9, ease: [0.19, 1, 0.22, 1] }}
                className="max-w-3xl text-4xl font-semibold tracking-tight text-white md:text-7xl"
              >
                Hey. You have been selected by our AI.
              </motion.h1>

              <motion.p
                initial={{ opacity: 0, y: 68 }}
                animate={{
                  opacity: showIntroCopy ? 1 : 0,
                  y: showIntroCopy ? 0 : 68,
                }}
                transition={{
                  duration: 0.85,
                  delay: 0.16,
                  ease: [0.19, 1, 0.22, 1],
                }}
                className="mt-6 max-w-2xl text-base leading-8 text-slate-300 md:text-xl"
              >
                Small focused steps become systems. Systems become leverage.
              </motion.p>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <div className="absolute inset-0 z-20 flex flex-col">
        <AnimatePresence>
          {phase === "form" ? (
            <motion.div
              key="window-controls"
              initial={{ opacity: 0, y: -24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            >
              <MinimalHeader />
            </motion.div>
          ) : null}
        </AnimatePresence>

        <AnimatePresence>
          {phase === "form" ? (
            <motion.main
              key="form-shell"
              initial={{ opacity: 0, y: 24, scale: 0.985 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
              className="flex flex-1 items-center justify-center px-4 pb-5 md:px-6 md:pb-6 xl:px-8"
            >
              <div
                onMouseMove={handleShellMouseMove}
                onMouseLeave={handleShellMouseLeave}
                className="relative h-full max-h-[calc(100vh-5rem)] w-full max-w-[92rem] overflow-hidden rounded-[34px] border border-white/10 bg-[rgba(9,12,24,0.56)] shadow-[0_30px_90px_rgba(0,0,0,0.36)] backdrop-blur-2xl"
              >
                {!isSummarySection ? (
                  <>
                    <div
                      className="absolute inset-y-0 left-0 z-20 w-8"
                      onMouseEnter={() => setIsSidebarNearEdge(true)}
                    />

                    <button
                      type="button"
                      aria-label={
                        isSidebarPinned ? "Hide sections" : "Show sections"
                      }
                      title={
                        isSidebarPinned ? "Hide sections" : "Show sections"
                      }
                      onMouseEnter={() => setIsSidebarHovering(true)}
                      onMouseLeave={() => {
                        if (!isSidebarPinned) {
                          setIsSidebarHovering(false);
                        }
                      }}
                      onClick={handleSidebarToggle}
                      className={`absolute left-5 top-5 z-40 inline-flex h-11 w-11 items-center justify-center rounded-full border transition-all ${
                        isSidebarOpen
                          ? "border-cyan-300/45 bg-cyan-300/14 text-cyan-50 shadow-[0_12px_32px_rgba(34,211,238,0.18)]"
                          : "border-white/12 bg-white/8 text-slate-200 hover:border-white/24 hover:bg-white/12"
                      }`}
                    >
                      <Menu size={16} />
                    </button>

                    <motion.aside
                      initial={false}
                      animate={{
                        x: isSidebarOpen ? 0 : -376,
                        opacity: isSidebarOpen ? 1 : 0.92,
                      }}
                      transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
                      onMouseEnter={() => setIsSidebarHovering(true)}
                      onMouseLeave={() => {
                        if (!isSidebarPinned) {
                          setIsSidebarHovering(false);
                        }
                      }}
                      className="absolute inset-y-0 left-0 z-30 flex w-[23rem] min-h-0 flex-col overflow-y-auto border-r border-white/10 bg-[linear-gradient(180deg,rgba(11,15,30,0.96),rgba(5,8,18,0.92))] p-6 shadow-[0_30px_70px_rgba(0,0,0,0.34)] onboarding-scrollbar md:p-8"
                    >
                      <div>
                        <div className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-white/6 px-4 py-2 text-[11px] uppercase tracking-[0.3em] text-slate-300">
                          <Sparkles size={14} />
                          Onboarding
                        </div>
                        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-white md:text-4xl">
                          Build your Spark profile one screen at a time.
                        </h1>
                        <p className="mt-4 max-w-md text-sm leading-7 text-slate-300">
                          The sidebar stays hidden until you hover the left edge
                          or open it with the top toggle.
                        </p>

                        <div className="mt-8">
                          <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.24em] text-slate-400">
                            <span>{section.eyebrow}</span>
                            <span>
                              {currentSectionIndex + 1} / {sections.length}
                            </span>
                          </div>
                          <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                            <motion.div
                              className="h-full rounded-full bg-[linear-gradient(90deg,#22d3ee,#a5f3fc)]"
                              animate={{ width: `${progressValue}%` }}
                              transition={{
                                duration: 0.45,
                                ease: [0.22, 1, 0.36, 1],
                              }}
                            />
                          </div>
                        </div>
                        <div className="mt-8">
                          <p className="text-[11px] uppercase tracking-[0.24em] text-slate-400">
                            Sections
                          </p>
                          <div className="mt-4 space-y-2">
                            {sectionProgress.map((item) => (
                              <button
                                key={item.id}
                                type="button"
                                disabled={!item.unlocked || item.isCurrent}
                                onClick={() => moveToSection(item.index)}
                                className={`flex w-full items-center gap-3 rounded-[20px] border px-4 py-3 text-left transition-all ${
                                  item.isCurrent
                                    ? "border-cyan-300/40 bg-cyan-300/10"
                                    : item.unlocked
                                      ? "border-white/10 bg-white/5 hover:border-white/22 hover:bg-white/8"
                                      : "border-white/6 bg-white/4 opacity-55"
                                }`}
                              >
                                <div
                                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold ${
                                    item.completed
                                      ? "border-emerald-300/35 bg-emerald-300/12 text-emerald-100"
                                      : item.isCurrent
                                        ? "border-cyan-300/35 bg-cyan-300/12 text-cyan-100"
                                        : "border-white/10 text-slate-400"
                                  }`}
                                >
                                  {item.completed ? (
                                    <Check size={12} />
                                  ) : (
                                    item.index + 1
                                  )}
                                </div>
                                <div className="min-w-0 flex-1">
                                  <p className="truncate text-sm font-semibold text-white">
                                    {item.title}
                                  </p>
                                  <p className="mt-0.5 text-[10px] uppercase tracking-[0.18em] text-slate-500">
                                    {item.completed
                                      ? "Completed"
                                      : item.isCurrent
                                        ? "Current"
                                        : item.unlocked
                                          ? "Available"
                                          : "Locked"}
                                  </p>
                                </div>
                              </button>
                            ))}
                          </div>
                        </div>

                        <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-1">
                          <SummaryCard
                            label="Name"
                            value={draft.preferredName.trim() || "Waiting"}
                          />
                          <SummaryCard
                            label="Heard about"
                            value={
                              selectedHeardAboutLabel === "Not set"
                                ? "Waiting"
                                : selectedHeardAboutLabel
                            }
                          />
                          <SummaryCard
                            label="Language"
                            value={selectedLanguageLabel || "Waiting"}
                          />
                          <SummaryCard
                            label="Voice"
                            value={
                              selectedVoiceDisplayName
                                ? `${selectedVoiceDisplayName} ${draft.aiGender ? `(${prettifyValue(draft.aiGender)})` : ""}`.trim()
                                : "Waiting"
                            }
                          />
                          <SummaryCard
                            label="API keys"
                            value={`${totalApiKeys}`}
                          />
                        </div>
                      </div>
                    </motion.aside>
                  </>
                ) : null}

                <section
                  className={`flex h-full min-h-0 flex-col ${
                    isSummarySection
                      ? "px-6 py-8 md:px-10 xl:px-14 xl:py-12"
                      : "p-6 pt-20 md:p-8 md:pt-24 xl:px-12 xl:py-10 xl:pt-24"
                  }`}
                >
                  <div className="relative min-h-0 flex-1 overflow-hidden">
                    <AnimatePresence mode="wait" custom={direction}>
                      <motion.article
                        key={section.id}
                        custom={direction}
                        variants={sectionVariants}
                        initial="enter"
                        animate="center"
                        exit="exit"
                        transition={{
                          duration: 0.48,
                          ease: [0.22, 1, 0.36, 1],
                        }}
                        className="absolute inset-0 overflow-y-auto pr-2 onboarding-scrollbar"
                      >
                        <div
                          className={
                            isSummarySection
                              ? "mx-auto w-full max-w-6xl"
                              : "w-full"
                          }
                        >
                          {renderSectionBody()}
                        </div>
                      </motion.article>
                    </AnimatePresence>
                  </div>

                  <div
                    className={`mt-8 flex flex-col gap-3 border-t border-white/10 pt-6 sm:flex-row sm:items-center ${
                      isSummarySection
                        ? "sm:justify-center"
                        : "sm:justify-between"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => void handleBack()}
                      disabled={isSubmitting}
                      className="inline-flex items-center justify-center gap-2 rounded-full border border-white/14 px-5 py-3 text-sm font-medium text-slate-200 transition-all hover:border-white/28 hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <ArrowLeft size={16} />
                      {currentSectionIndex === 0
                        ? hasAuthenticatedSession
                          ? "Skip for now"
                          : "Back to welcome"
                        : "Previous section"}
                    </button>

                    {section.id === "summary" ? (
                      <RippleButton
                        onClick={() => void handleComplete()}
                        disabled={isSubmitting}
                        className="min-w-[300px] rounded-full px-7 py-3.5 font-semibold text-slate-950"
                        rippleColor="#67E8F9"
                        style={{
                          background:
                            "linear-gradient(135deg, rgba(103,232,249,0.96), rgba(244,251,255,0.94))",
                          borderColor: "rgba(165,243,252,0.82)",
                          boxShadow:
                            "0 22px 48px rgba(34,211,238,0.28), inset 0 1px 0 rgba(255,255,255,0.45)",
                          textShadow: "none",
                        }}
                      >
                        {isSubmitting
                          ? "Syncing profile..."
                          : hasAuthenticatedSession
                            ? "Save and launch Spark"
                            : "Create account to continue"}
                      </RippleButton>
                    ) : (
                      <RippleButton
                        onClick={handleNext}
                        disabled={isSubmitting}
                        className="min-w-60 rounded-full px-7 py-3.5 font-semibold text-slate-950"
                        rippleColor="#67E8F9"
                        style={{
                          background:
                            "",
                          // borderColor: "rgba(165,243,252,0.82)",
                          boxShadow:
                            "0 20px 44px rgba(34,211,238,0.24), inset 0 1px 0 rgba(255,255,255,0.4)",
                          textShadow: "none",
                        }}
                      >
                        <span className="inline-flex items-center gap-2">
                          Next section
                          <ArrowRight size={16} />
                        </span>
                      </RippleButton>
                    )}
                  </div>
                </section>
              </div>
            </motion.main>
          ) : null}
        </AnimatePresence>
      </div>

      <style>{`
        .onboarding-scrollbar {
          scroll-behavior: smooth;
          scrollbar-width: thin;
          scrollbar-color: rgba(103, 232, 249, 0.45) transparent;
        }

        .onboarding-scrollbar::-webkit-scrollbar {
          width: 8px;
        }

        .onboarding-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }

        .onboarding-scrollbar::-webkit-scrollbar-thumb {
          background: linear-gradient(180deg, rgba(103, 232, 249, 0.52), rgba(148, 163, 184, 0.3));
          border-radius: 999px;
          border: 2px solid transparent;
        }

        .onboarding-scrollbar::-webkit-scrollbar-thumb:hover {
          background: linear-gradient(180deg, rgba(103, 232, 249, 0.68), rgba(226, 232, 240, 0.34));
        }
      `}</style>
    </div>
  );
}

export default Onboarding;
