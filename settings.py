"""Settings shared by the harness and tools."""

MODEL = "vertex_ai/gemini-3.5-flash-lite"  # chat and photo scanning
VERTEX_LOCATION = "global"

# A stuck connection should fail fast and retry once, not hang the page for LiteLLM's 10-minute default.
MODEL_TIMEOUT = 45  # seconds per call
MODEL_RETRIES = 1
