⭐ 8. WANT ME TO GENERATE:

✔ Dockerfile
✔ docker-compose
✔ prod_start.sh
✔ systemd service for Linux
✔ Model warm-up code
✔ Async model worker pattern
✔ Model caching for super-low latency

3 mkdir -p "$MODEL_DIR"


# Helper: clone if missing
maybe_clone() {
repo_url="$1"
dir="$2"
if [ ! -d "$dir" ]; then
echo "[models] Cloning $repo_url -> $dir"
git lfs install --skip-smudge
# Use git clone with LFS disabled smudge then fetch heavy files with aria2 (optional)
git clone "$repo_url" "$dir" || exit 1
# Optionally: download large files directly with aria2 if needed
else
echo "[models] Found: $dir"
fi
}


# Example models — adapt to the ones you actually need
maybe_clone https://huggingface.co/BAAI/bge-m3 "$MODEL_DIR/bge-m3"
maybe_clone https://huggingface.co/openai/whisper-small "$MODEL_DIR/whisper-small"
maybe_clone https://huggingface.co/SamLowe/roberta-base-go_emotions "$MODEL_DIR/go-emotion"


# Set HF env to skip auto-conversion if using transformers
export HF_HUB_DISABLE_AUTO_CONVERSION=1


# Start server (uvicorn) — use workers=1 to avoid multiple processes loading models twice
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
