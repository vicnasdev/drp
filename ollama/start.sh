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
MODEL="${OLLAMA_MODEL:-gemma3:1b}"
echo "Pulling model: $MODEL"
ollama pull "$MODEL"

# Warm up: load model into RAM so first real request is fast
echo "Warming up model..."
curl -sf http://localhost:${PORT:-11434}/api/generate \
  -d "{\"model\": \"$MODEL\", \"prompt\": \"hi\", \"stream\": false}" \
  > /dev/null 2>&1 || true
echo "Model warm — ready for traffic"

# Keep container alive (ollama serve is backgrounded)
wait
