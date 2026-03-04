from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openrouter_api_key: str
    gemini_api_key: str
    ELEVEN_LABS_API_KEY: str
    gemini_model_name: str
    openrouter_light_model_name: str 
    openrouter_reasoning_model_name: str 
    port : int
    default_lang: str = "en"
    pinecone_api_key: str
    pinecone_env: str
    pinecone_index_name: str
    pinecone_metadata_namespace: str
    word_matching_threshold: float = 0.35
    ai_name: str = "SPARK"
    mongo_uri : str 
    upstash_redis_rest_url : str
    upstash_redis_rest_token : str
    # environment : str = "production"
    environment : str = "desktop"
    # environment : str = "development"
    db_name : str = "spark"
    nep_voice_male : str = "ne-NP-SagarNeural"
    nep_voice_female : str = "ne-NP-HemkalaNeural"
    hindi_voice_male : str = "hi-IN-MadhurNeural"
    hindi_voice_female : str = "hi-IN-SwaraNeural"
    eng_voice_male : str = "en-US-BrianNeural"
    eng_voice_female : str = "en-US-JennyNeural"
    groq_mode: bool = True
    GROQ_DEFAULT_MODEL : str = "meta-llama/llama-4-scout-17b-16e-instruct"
    GROQ_REASONING_MODEL: str = "openai/gpt-oss-20b"

    HUGGINGFACE_API_ACCESS_TOKEN: str
    TOOLS_CDN_ENABLED: bool = False
    TOOLS_CDN_MANIFEST_URL: str = ""
    TOOLS_CDN_PACKAGE_URL: str = ""

    # Stream/TTS rollout flags
    STREAM_ONE_SHOT_TTS_ENABLED: bool = True
    STREAM_FAST_ACK_ENABLED: bool = True
    STREAM_USE_LLM_STREAM: bool = True
    STREAM_USE_COMPACT_PROMPT: bool = True
    STREAM_GROQ_FAST_MODEL: str = "llama-3.1-8b-instant"
    STREAM_CONTEXT_BUDGET_MS: int = 200
    STREAM_FIRST_AUDIO_SLO_MS: int = 1000
    STREAM_CHUNK_MIN_WORDS: int = 5
    STREAM_CHUNK_SOFT_WORDS: int = 12
    STREAM_CHUNK_MAX_WORDS: int = 30
    STREAM_QUERY_CONTEXT_TTL_SECONDS: int = 30
    STREAM_QUERY_CONTEXT_CACHE_SIZE: int = 512
    FINAL_STATE_SUMMARY_TTS_ENABLED: bool = True
    FINAL_STATE_SUMMARY_LLM_TIMEOUT_MS: int = 1000
    SQH_PLAN_RETRY_ATTEMPTS: int = 1

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings() # type: ignore
