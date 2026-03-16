"""Universal LLM adapter — covers all services via raw HTTP.

Strategy (Cherry Studio approach):
  • All OpenAI-compatible services  → POST {base_url}/chat/completions
  • Anthropic (api.anthropic.com)   → POST {base_url}/v1/messages  (auto-detected)

No SDK dependencies.  Works with: OpenAI, DeepSeek, Moonshot, Qwen, Zhipu GLM,
MiniMax, SiliconFlow, Yi, StepFun, Spark, HunYuan, Groq, Mistral, Together AI,
Google Gemini (OpenAI-compat endpoint), Ollama (/v1), any OpenAI-compatible proxy,
and Anthropic Claude (native API, auto-detected by base_url).
"""

import requests
from .base import BaseLLM, LLMConfig

# ── Constants ────────────────────────────────────────────────────

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT   = 120


# ── Helper ───────────────────────────────────────────────────────

def _extract_error(resp: requests.Response) -> str:
    """Best-effort error message from an HTTP error response."""
    try:
        body = resp.json()
        return (
            body.get("error", {}).get("message")
            or body.get("message")
            or str(body)
        )
    except Exception:
        return resp.text[:300] or resp.reason or str(resp.status_code)


# ── Adapter ──────────────────────────────────────────────────────

class OpenAIAdapter(BaseLLM):
    """Universal HTTP adapter — handles both OpenAI-format and Anthropic-format APIs."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)

    # ── Format detection ─────────────────────────────────────────

    def _is_anthropic(self) -> bool:
        return "anthropic.com" in self.config.base_url.lower()

    # ── URL helpers ──────────────────────────────────────────────

    def _openai_endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def _anthropic_endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        # Ensure /v1 segment is present
        if not base.endswith("/v1"):
            base = base + "/v1"
        return base + "/messages"

    def chat_endpoint(self) -> str:
        """Public helper for UI preview."""
        if self._is_anthropic():
            return self._anthropic_endpoint()
        return self._openai_endpoint()

    # ── Core: OpenAI Chat Completions ─────────────────────────────

    def _call_openai(self, prompt: str, system_prompt: str) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":       self.config.model_name,
            "messages":    messages,
            "temperature": self.config.temperature,
            "max_tokens":  self.config.max_tokens,
        }

        try:
            resp = requests.post(
                self._openai_endpoint(),
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(
                f"无法连接到 {self._openai_endpoint()}\n"
                f"请检查 API 地址是否正确: {exc}"
            ) from exc
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"请求超时（{DEFAULT_TIMEOUT}s），请稍后重试"
            ) from None

        if not resp.ok:
            raise RuntimeError(
                f"HTTP {resp.status_code}: {_extract_error(resp)}\n"
                f"endpoint: {self._openai_endpoint()}"
            )

        raw = resp.text
        try:
            data = resp.json()
        except Exception:
            preview = raw[:300].strip() or "(空响应)"
            raise RuntimeError(
                f"API 返回了非 JSON 内容（HTTP {resp.status_code}）\n"
                f"endpoint: {self._openai_endpoint()}\n"
                f"响应内容: {preview}"
            ) from None

        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"响应结构异常，无法提取内容: {exc}\n"
                f"响应 JSON: {str(data)[:300]}"
            ) from exc

    # ── Core: Anthropic Messages ──────────────────────────────────

    def _call_anthropic(self, prompt: str, system_prompt: str) -> str:
        payload = {
            "model":      self.config.model_name,
            "max_tokens": self.config.max_tokens,
            "messages":   [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt
        if self.config.temperature is not None:
            payload["temperature"] = self.config.temperature

        try:
            resp = requests.post(
                self._anthropic_endpoint(),
                headers={
                    "x-api-key":         self.config.api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type":      "application/json",
                },
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(
                f"无法连接到 Anthropic API ({self._anthropic_endpoint()}): {exc}"
            ) from exc
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"请求超时（{DEFAULT_TIMEOUT}s），请稍后重试"
            ) from None

        if not resp.ok:
            raise RuntimeError(
                f"Anthropic HTTP {resp.status_code}: {_extract_error(resp)}\n"
                f"endpoint: {self._anthropic_endpoint()}"
            )

        raw = resp.text
        try:
            data = resp.json()
        except Exception:
            preview = raw[:300].strip() or "(空响应)"
            raise RuntimeError(
                f"Anthropic API 返回了非 JSON 内容（HTTP {resp.status_code}）\n"
                f"endpoint: {self._anthropic_endpoint()}\n"
                f"响应内容: {preview}"
            ) from None

        try:
            return data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"Anthropic 响应结构异常: {exc}\n"
                f"响应 JSON: {str(data)[:300]}"
            ) from exc

    # ── Public interface ──────────────────────────────────────────

    def complete(self, prompt: str, system_prompt: str = "") -> str:
        if self._is_anthropic():
            return self._call_anthropic(prompt, system_prompt)
        return self._call_openai(prompt, system_prompt)

    def test_connection(self) -> bool:
        """Probe the configured endpoint.  Raises RuntimeError with details on failure."""
        if not self.config.base_url:
            raise RuntimeError("API 地址为空，请填写完整地址（如 https://api.deepseek.com/v1）")
        if not self.config.api_key:
            raise RuntimeError("API 密钥为空，请填写 API Key")
        if not self.config.model_name:
            raise RuntimeError("模型名称为空，请填写模型名称（如 deepseek-chat）")
        result = self.complete("Hi", "Reply with one word: ok")
        return bool(result)
