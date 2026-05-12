"""
Dev launcher — starts Litestar app via uvicorn.
Usage: uv run main.py
       devbox shell → uv run main.py
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "wobsongo.api.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
