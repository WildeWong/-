"""Ollama local LLM adapter."""

import requests
from .base import BaseLLM, LLMConfig


class OllamaAdapter(BaseLLM):
    """Adapter for Ollama local REST API (http://localhost:11434)."""

    DEFAULT_MODEL = "llama3"
    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        if not self.config.base_url:
            self.config.base_url = self.DEFAULT_BASE_URL
        if not self.config.model_name:
            self.config.model_name = self.DEFAULT_MODEL

    def complete(self, prompt: str, system_prompt: str = "") -> str:
        base = self.config.base_url.rstrip("/")
        url = f"{base}/api/chat"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":    self.config.model_name,
            "messages": messages,
            "stream":   False,
            "options":  {"temperature": self.config.temperature},
        }

        try:
            resp = requests.post(url, json=payload, timeout=120)
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"无法连接到 Ollama ({url})，请确认 Ollama 已启动: {e}"
            ) from e

        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")

    def test_connection(self) -> bool:
        """Check if Ollama is running and the model exists. Raises on failure."""
        base = self.config.base_url.rstrip("/")
        try:
            resp = requests.get(f"{base}/api/tags", timeout=10)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"无法连接到 Ollama ({base})，请确认服务已启动: {e}"
            ) from e

        # Check if the target model is listed
        data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        if models and self.config.model_name not in models:
            available = "、".join(models[:5])
            raise RuntimeError(
                f"模型 '{self.config.model_name}' 不存在。"
                f"已安装模型: {available}"
            )
        return True
