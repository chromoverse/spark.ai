"""
ML Testing Routes - Test all models
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List
import tempfile
import os

from app.ml import model_loader, get_embedding, get_embeddings

router = APIRouter(prefix="/ml-test", tags=["ML Testing"])

# ==================== REQUEST MODELS ====================

class TextInput(BaseModel):
    text: str

class BatchTextInput(BaseModel):
    texts: List[str]

class SimilarityInput(BaseModel):
    text1: str
    text2: str

# ==================== EMBEDDING TESTS ====================

@router.post("/embedding/single")
async def test_single_embedding(input: TextInput):
    """
    Test: Generate embedding for single text
    
    Example:
    POST /ml-test/embedding/single
    {
        "text": "Hello, how are you?"
    }
    """
    try:
        embedding = await get_embedding(input.text)
        
        return {
            "success": True,
            "text": input.text,
            "embedding_dimension": len(embedding),
            "embedding_sample": embedding[:5],  # First 5 values
            "model": "bge-m3"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/embedding/batch")
async def test_batch_embeddings(input: BatchTextInput):
    """
    Test: Generate embeddings for multiple texts
    
    Example:
    POST /ml-test/embedding/batch
    {
        "texts": [
            "I love programming",
            "Python is amazing",
            "The weather is nice today"
        ]
    }
    """
    try:
        embeddings = await get_embeddings(input.texts)
        
        return {
            "success": True,
            "count": len(embeddings),
            "texts": input.texts,
            "embedding_dimension": len(embeddings[0]),
            "embeddings_sample": [emb[:5] for emb in embeddings],  # First 5 values each
            "model": "bge-m3"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/embedding/similarity")
async def test_similarity(input: SimilarityInput):
    """
    Test: Calculate similarity between two texts using embeddings
    
    Example:
    POST /ml-test/embedding/similarity
    {
        "text1": "I love cats",
        "text2": "I adore felines"
    }
    """
    try:
        import numpy as np
        
        # Get embeddings
        embeddings = await get_embeddings([input.text1, input.text2])
        
        # Calculate cosine similarity
        emb1 = np.array(embeddings[0])
        emb2 = np.array(embeddings[1])
        
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
        
        return {
            "success": True,
            "text1": input.text1,
            "text2": input.text2,
            "similarity_score": float(similarity),
            "interpretation": "Very similar" if similarity > 0.8 else "Somewhat similar" if similarity > 0.5 else "Not similar",
            "model": "bge-m3"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== EMOTION TESTS ====================

@router.post("/emotion/analyze")
async def test_emotion(input: TextInput):
    """
    Test: Detect emotion in text
    
    Example:
    POST /ml-test/emotion/analyze
    {
        "text": "I am so happy today!"
    }
    """
    try:
        emotion_model = model_loader.get_model("emotion")
        
        if not emotion_model:
            raise HTTPException(status_code=503, detail="Emotion model not loaded")
        
        result = emotion_model(input.text)[0]
        
        return {
            "success": True,
            "text": input.text,
            "emotion": result["label"],
            "confidence": round(result["score"], 4),
            "model": "emotion-roberta"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/emotion/batch")
async def test_emotion_batch(input: BatchTextInput):
    """
    Test: Detect emotions in multiple texts
    
    Example:
    POST /ml-test/emotion/batch
    {
        "texts": [
            "I'm so excited!",
            "This makes me sad.",
            "I'm feeling angry."
        ]
    }
    """
    try:
        emotion_model = model_loader.get_model("emotion")
        
        if not emotion_model:
            raise HTTPException(status_code=503, detail="Emotion model not loaded")
        
        results = emotion_model(input.texts)
        
        analyzed = [
            {
                "text": text,
                "emotion": result["label"],
                "confidence": round(result["score"], 4)
            }
            for text, result in zip(input.texts, results)
        ]
        
        return {
            "success": True,
            "count": len(analyzed),
            "results": analyzed,
            "model": "emotion-roberta"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== WHISPER TESTS ====================

@router.post("/whisper/transcribe")
async def test_transcribe(file: UploadFile = File(...)):
    """
    Test: Transcribe audio file to text
    
    Example:
    POST /ml-test/whisper/transcribe
    - Upload an audio file (.wav, .mp3, .m4a, etc.)
    """
    try:
        whisper_model = model_loader.get_model("whisper")
        
        if not whisper_model:
            raise HTTPException(status_code=503, detail="Whisper model not loaded")
        
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        try:
            # Transcribe
            segments, info = whisper_model.transcribe(tmp_path, beam_size=5)
            
            # Collect all segments
            transcription_segments = []
            full_text = []
            
            for segment in segments:
                transcription_segments.append({
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text
                })
                full_text.append(segment.text)
            
            return {
                "success": True,
                "filename": file.filename,
                "full_text": " ".join(full_text),
                "segments": transcription_segments,
                "language": info.language,
                "language_probability": round(info.language_probability, 4),
                "duration": round(info.duration, 2),
                "model": "whisper-small"
            }
        finally:
            # Clean up temp file
            os.unlink(tmp_path)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/whisper/detect-language")
async def test_detect_language(file: UploadFile = File(...)):
    """
    Test: Detect language from audio file
    
    Example:
    POST /ml-test/whisper/detect-language
    - Upload an audio file
    """
    try:
        whisper_model = model_loader.get_model("whisper")
        
        if not whisper_model:
            raise HTTPException(status_code=503, detail="Whisper model not loaded")
        
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        try:
            # Detect language (only transcribe first 30 seconds)
            segments, info = whisper_model.transcribe(tmp_path, beam_size=5)
            
            # Get first segment for sample
            first_segment = next(segments, None)
            sample_text = first_segment.text if first_segment else ""
            
            return {
                "success": True,
                "filename": file.filename,
                "detected_language": info.language,
                "confidence": round(info.language_probability, 4),
                "sample_text": sample_text,
                "duration": round(info.duration, 2),
                "model": "whisper-small"
            }
        finally:
            os.unlink(tmp_path)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== HEALTH CHECK ====================

@router.get("/health")
async def test_health():
    """
    Test: Check if all models are loaded
    """
    loaded_models = list(model_loader._models.keys())
    available_models = list(model_loader.MODELS_CONFIG.keys())
    
    status = {
        "embedding": "embedding" in loaded_models,
        "whisper": "whisper" in loaded_models,
        "emotion": "emotion" in loaded_models
    }
    
    all_loaded = all(status.values())
    
    return {
        "success": all_loaded,
        "status": status,
        "loaded_models": loaded_models,
        "available_models": available_models,
        "device": model_loader.DEVICE
    }