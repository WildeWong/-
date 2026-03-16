from .models import Scene, SceneList
from .detector import SceneDetector

__all__ = ["Scene", "SceneList", "SceneDetector", "LLMSceneDetector"]


def __getattr__(name: str):
    if name == "LLMSceneDetector":
        from .llm_detector import LLMSceneDetector
        return LLMSceneDetector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
