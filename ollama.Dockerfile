# ollama.Dockerfile — Ollama server with cloud auth + embedding model pre-pull
#
# Build:
#   docker build -f ollama.Dockerfile -t wobsongo-ollama .
#
# Required env vars:
#   OLLAMA_API_KEY      Ollama Cloud bearer token (from ollama login)
#   OLLAMA_EMBED_MODEL  Local embedding model to pull on first start
#                       (e.g. embeddinggemma:300m)
#
# The /root/.ollama volume persists credentials and model weights across restarts.
# Cloud models (e.g. gemma4:31b-cloud) stream from Ollama Cloud — no local storage needed.

FROM ollama/ollama

COPY ollama-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
