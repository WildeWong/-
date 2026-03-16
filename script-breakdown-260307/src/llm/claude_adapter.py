"""Anthropic Claude API adapter."""

from .base import BaseLLM, LLMConfig


class ClaudeAdapter(BaseLLM):
    """Adapter for Anthropic Claude API."""

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        if not self.config.model_name:
            self.config.model_name = self.DEFAULT_MODEL

    def _get_client(self):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic 包未安装，请运行: pip install anthropic"
            )
        kwargs = {"api_key": self.config.api_key}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        return anthropic.Anthropic(**kwargs)

    def complete(self, prompt: str, system_prompt: str = "") -> str:
        client = self._get_client()
        kwargs = {
            "model":    self.config.model_name,
            "max_tokens": self.config.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature

        response = client.messages.create(**kwargs)
        return response.content[0].text

    def test_connection(self) -> bool:
        """Probe the API. Raises on failure so the caller sees the real error."""
        if not self.config.api_key:
            raise RuntimeError("API 密钥为空，请填写 Anthropic API Key")
        result = self.complete("Hi", "Reply with one word: ok")
        return bool(result)
