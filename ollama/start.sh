#!/bin/bash
set -e

# Start Ollama in the background
ollama serve &

# Wait for it to become ready
echo "Waiting for Ollama..."
for i in $(seq 1 30); do
    if ollama list > /dev/null 2>&1; then
        echo "Ollama ready"
        break
    fi
    sleep 1
done

# Ensure the configured model is present
# (no-op if already baked into the image)
MODEL="${OLLAMA_MODEL:-qwen2.5:0.5b}"
echo "Loading model: $MODEL"
ollama pull "$MODEL"

# Hand off to the auth proxy as PID 1
exec python3 /proxy.py
