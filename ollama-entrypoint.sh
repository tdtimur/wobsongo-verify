#!/bin/bash
# Ollama container entrypoint.
#
# On first start:
#   1. Writes cloud credentials from OLLAMA_API_KEY into ~/.ollama/credentials
#   2. Starts the Ollama server
#   3. Pulls the local embedding model (OLLAMA_EMBED_MODEL)
#
# On subsequent starts the volume already has credentials + model weights,
# so the pull is skipped and the server starts immediately.

set -euo pipefail

CREDENTIALS="${HOME}/.ollama/credentials"

# Write cloud auth credentials on first start
if [ -n "${OLLAMA_API_KEY:-}" ] && [ ! -f "$CREDENTIALS" ]; then
    echo "Writing Ollama Cloud credentials..."
    mkdir -p "$(dirname "$CREDENTIALS")"
    printf '{"token":"%s"}' "$OLLAMA_API_KEY" > "$CREDENTIALS"
    chmod 600 "$CREDENTIALS"
fi

# Start Ollama server in background
ollama serve &
SERVER_PID=$!

# Wait for the server to accept requests (up to 60s)
echo "Waiting for Ollama server to be ready..."
for i in $(seq 1 60); do
    if ollama list >/dev/null 2>&1; then
        echo "Ollama server ready."
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: Ollama server did not start in time." >&2
        exit 1
    fi
    sleep 1
done

# Pull models that are not already present
pull_if_missing() {
    local model="$1"
    if ollama list | grep -q "^${model}"; then
        echo "${model} already present."
    else
        echo "Pulling ${model}..."
        ollama pull "${model}"
    fi
}

[ -n "${OLLAMA_MODEL:-}" ]       && pull_if_missing "${OLLAMA_MODEL}"
[ -n "${OLLAMA_EMBED_MODEL:-}" ] && pull_if_missing "${OLLAMA_EMBED_MODEL}"

echo "Setup complete. Ollama is serving."
wait "$SERVER_PID"
