FROM ollama/ollama:latest

COPY start.sh /
RUN chmod +x /start.sh

# Pre-pull default model so deploys start instantly.
# Override at build time:  docker build --build-arg OLLAMA_MODEL=qwen2.5:0.5b
ARG OLLAMA_MODEL=qwen2.5:0.5b
ENV OLLAMA_MODEL=${OLLAMA_MODEL}
RUN /bin/bash -c "ollama serve & sleep 10 && ollama pull ${OLLAMA_MODEL}; kill %1 2>/dev/null; exit 0"

EXPOSE 11434
ENTRYPOINT ["/start.sh"]
