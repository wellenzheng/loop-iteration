"""Thin OpenAI-compatible chat client used by the judge. Reads creds from env
(OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL). No hardcoded keys."""
from __future__ import annotations
import os
import httpx

def chat(prompt: str, model: str | None = None, timeout: float = 120.0) -> str:
    base = os.environ.get("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    key = os.environ.get("OPENAI_API_KEY", "")
    model = model or os.environ.get("OPENAI_MODEL", "glm-4.7")
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.1, "max_tokens": 512},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
