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
    environment : str = "development"
    db_name : str = "spark"
    nep_voice_male : str = "ne-NP-SagarNeural"
    nep_voice_female : str = "ne-NP-HemkalaNeural"
    hindi_voice_male : str = "hi-IN-MadhurNeural"
    hindi_voice_female : str = "hi-IN-SwaraNeural"
    eng_voice_male : str = "en-US-BrianNeural"
    eng_voice_female : str = "en-US-JennyNeural"

    HUGGINGFACE_API_ACCESS_TOKEN: str

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings() # type: ignore