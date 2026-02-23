#!/bin/bash
set -e

# Railway sets PORT; Ollama must listen on it.
export OLLAMA_HOST="0.0.0.0:${PORT:-11434}"

# Start Ollama in the background
ollama serve &

# Wait for it to become ready
echo "Waiting for Ollama..."
for i in $(seq 1 30); do
    if ollama list > /dev/null 2>&1; then
        echo "Ollama ready on :${PORT:-11434}"
        break
    fi
    sleep 1
done

# Ensure the configured model is present
# (no-op if already baked into the image)
MODEL="${OLLAMA_MODEL:-qwen2.5:0.5b}"
echo "Pulling model: $MODEL"
ollama pull "$MODEL"

# Keep container alive (ollama serve is backgrounded)
wait
