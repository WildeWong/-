from .base import BaseLLM, LLMConfig

__all__ = ["BaseLLM", "LLMConfig", "ClaudeAdapter", "OpenAIAdapter", "OllamaAdapter"]


def __getattr__(name: str):
    if name == "ClaudeAdapter":
        from .claude_adapter import ClaudeAdapter
        return ClaudeAdapter
    if name == "OpenAIAdapter":
        from .openai_adapter import OpenAIAdapter
        return OpenAIAdapter
    if name == "OllamaAdapter":
        from .ollama_adapter import OllamaAdapter
        return OllamaAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
