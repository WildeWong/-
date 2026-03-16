"""Singleton application state, replacing MainWindow instance variables."""
import copy
import threading
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from ..parsers.base import ParseResult
from ..scene.models import Scene, SceneList
from ..llm.base import LLMConfig
from ..schedule.models import (
    ProductionSchedule, ScheduleConfig, ActorSchedule, LocationInfo, ScheduleSnapshot,
)

if TYPE_CHECKING:
    from .project import Project


MAX_UNDO_STEPS = 50


@dataclass
class LLMTask:
    """Tracks a running LLM background task."""
    task_type: str = ""       # "detect", "summarize", "extract", "analyze_character", "analyze_all"
    status: str = "idle"      # "idle", "running", "done", "error"
    result: object = None
    error: str = ""
    scene_index: int = -1     # for summarize / per-scene tasks


class AppState:
    """Singleton holding all application state."""

    _instance: Optional["AppState"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.parse_result: Optional[ParseResult] = None
        self.scene_list: Optional[SceneList] = None
        self.llm_config: LLMConfig = LLMConfig()
        self.llm_task: LLMTask = LLMTask()
        self.filename: str = ""
        self.status_message: str = "就绪 - 请导入剧本文件"
        self.content_locked: bool = False
        self._lock = threading.Lock()

        # Undo / Redo stacks
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []

        # Entity extraction results
        # {scene_index: {"characters": [...], "props": [...], "scene_type": ""}}
        self.entities: dict = {}
        # {"characters": [{"name": str, "scenes": [int], "description": str}],
        #  "props": [{"name": str, "scenes": [int]}]}
        self.global_entities: dict = {"characters": [], "props": []}

        # Character analysis results
        # {character_name: analysis_text}
        self.character_analyses: dict = {}
        # Global analysis text
        self.global_analysis: str = ""

        # Episode-level synopsis (LLM-generated or user-written)
        self.episode_synopsis: str = ""

        # Multi-episode project support
        self.project: Optional["Project"] = None
        self.current_episode_id: str = ""

        # Schedule (排期) module
        self.schedule: Optional[ProductionSchedule] = None
        self.schedule_snapshots: list[ScheduleSnapshot] = []
        self.schedule_task: LLMTask = LLMTask()
        # Preference learner — lazily initialised by _get_learner() in app.py
        self.preference_learner = None

    def reset(self):
        """Reset state for a new file (clears project context too)."""
        self.parse_result = None
        self.scene_list = None
        self.filename = ""
        self.llm_task = LLMTask()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.entities.clear()
        self.global_entities = {"characters": [], "props": []}
        self.character_analyses.clear()
        self.global_analysis = ""
        self.episode_synopsis = ""
        self.project = None
        self.current_episode_id = ""
        self.schedule = None
        self.schedule_snapshots = []
        self.schedule_task = LLMTask()

    # ── Undo / Redo ─────────────────────────────────────────────

    def snapshot(self) -> Optional[dict]:
        """Serialize current state to a restorable dict."""
        if not self.scene_list:
            return None
        scenes = []
        for s in self.scene_list:
            scenes.append({
                "scene_number": s.scene_number,
                "heading": s.heading,
                "location": s.location,
                "time_of_day": s.time_of_day,
                "int_ext": s.int_ext,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "content": s.content,
                "summary": s.summary,
                "scene_type": s.scene_type,
                "is_manually_adjusted": s.is_manually_adjusted,
                "confidence": s.confidence,
            })
        return {
            "scenes": scenes,
            "entities": copy.deepcopy(self.entities),
            "global_entities": copy.deepcopy(self.global_entities),
            "character_analyses": copy.deepcopy(self.character_analyses),
            "global_analysis": self.global_analysis,
            # Include raw lines so undo restores them after line-deletion ops
            "lines": list(self.parse_result.lines) if self.parse_result else [],
        }

    def _restore_snapshot(self, snapshot) -> None:
        """Restore state from a snapshot. Handles both old (list) and new (dict) formats."""
        if isinstance(snapshot, list):
            scene_dicts = snapshot
        else:
            scene_dicts = snapshot.get("scenes", [])
            self.entities = copy.deepcopy(snapshot.get("entities", {}))
            self.global_entities = copy.deepcopy(
                snapshot.get("global_entities", {"characters": [], "props": []})
            )
            self.character_analyses = copy.deepcopy(snapshot.get("character_analyses", {}))
            self.global_analysis = snapshot.get("global_analysis", "")

        scenes = []
        for d in scene_dicts:
            scenes.append(Scene(
                scene_number=d["scene_number"],
                heading=d["heading"],
                location=d.get("location", ""),
                time_of_day=d.get("time_of_day", ""),
                int_ext=d.get("int_ext", ""),
                start_line=d["start_line"],
                end_line=d["end_line"],
                content=d.get("content", ""),
                summary=d.get("summary", ""),
                scene_type=d.get("scene_type", ""),
                is_manually_adjusted=d.get("is_manually_adjusted", False),
                confidence=d.get("confidence", 1.0),
            ))
        self.scene_list = SceneList(scenes)

        # Restore raw lines if present (needed for undo of line-deletion ops)
        if "lines" in snapshot and snapshot["lines"] is not None:
            from ..parsers.base import ParseResult as _PR
            meta = self.parse_result.metadata if self.parse_result else {}
            self.parse_result = _PR(lines=snapshot["lines"], metadata=meta)

    def push_undo(self) -> None:
        """Save current state to undo stack before a mutation. Clears redo stack."""
        snap = self.snapshot()
        if snap is not None:
            self._undo_stack.append(snap)
            if len(self._undo_stack) > MAX_UNDO_STEPS:
                self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> bool:
        """Undo last change. Returns True if successful."""
        if not self._undo_stack:
            return False
        # Save current state to redo stack
        current = self.snapshot()
        if current is not None:
            self._redo_stack.append(current)
        # Restore from undo stack
        snap = self._undo_stack.pop()
        self._restore_snapshot(snap)
        self.status_message = "已撤销"
        return True

    def redo(self) -> bool:
        """Redo last undone change. Returns True if successful."""
        if not self._redo_stack:
            return False
        # Save current state to undo stack
        current = self.snapshot()
        if current is not None:
            self._undo_stack.append(current)
        # Restore from redo stack
        snap = self._redo_stack.pop()
        self._restore_snapshot(snap)
        self.status_message = "已恢复"
        return True

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    # ── Entity helpers ──────────────────────────────────────────

    def rebuild_global_entities(self) -> None:
        """Rebuild global_entities from per-scene entities."""
        char_map: dict[str, dict] = {}  # name -> {name, scenes, description}
        prop_map: dict[str, dict] = {}  # name -> {name, scenes}

        for idx_str, ent in self.entities.items():
            idx = int(idx_str) if isinstance(idx_str, str) else idx_str
            for name in ent.get("characters", []):
                if name not in char_map:
                    char_map[name] = {"name": name, "scenes": [], "description": ""}
                if idx not in char_map[name]["scenes"]:
                    char_map[name]["scenes"].append(idx)
            for name in ent.get("props", []):
                if name not in prop_map:
                    prop_map[name] = {"name": name, "scenes": []}
                if idx not in prop_map[name]["scenes"]:
                    prop_map[name]["scenes"].append(idx)

        # Sort by number of scene appearances (descending)
        self.global_entities = {
            "characters": sorted(char_map.values(), key=lambda c: len(c["scenes"]), reverse=True),
            "props": sorted(prop_map.values(), key=lambda p: len(p["scenes"]), reverse=True),
        }

    def rename_entity(self, old_name: str, new_name: str, entity_type: str) -> None:
        """Rename an entity (character or prop) globally across all scenes."""
        key = "characters" if entity_type == "character" else "props"
        for ent in self.entities.values():
            lst = ent.get(key, [])
            if old_name in lst:
                # Replace and deduplicate while preserving order
                seen: set = set()
                deduped = []
                for x in (new_name if x == old_name else x for x in lst):
                    if x not in seen:
                        seen.add(x)
                        deduped.append(x)
                ent[key] = deduped
        self.rebuild_global_entities()

    def remove_entity(self, name: str, entity_type: str) -> None:
        """Remove an entity globally from all scenes."""
        key = "characters" if entity_type == "character" else "props"
        for ent in self.entities.values():
            ent[key] = [x for x in ent.get(key, []) if x != name]
        self.rebuild_global_entities()

    def reindex_entities(self, old_to_new: dict) -> None:
        """Reindex entities dict after scenes are removed/renumbered.

        old_to_new maps old scene index (int) -> new scene index (int).
        Indices not in the mapping were deleted and their data is discarded.
        """
        new_entities: dict = {}
        for old_idx, new_idx in old_to_new.items():
            # Handle both int and string-keyed entities
            if old_idx in self.entities:
                new_entities[new_idx] = self.entities[old_idx]
            elif str(old_idx) in self.entities:
                new_entities[new_idx] = self.entities[str(old_idx)]
        self.entities = new_entities
        self.rebuild_global_entities()

    # ── Project / Episode Integration ───────────────────────────

    def save_to_episode(self) -> None:
        """Persist current AppState into the active EpisodeState on disk."""
        if not self.project or not self.current_episode_id:
            return

        from .project import EpisodeState
        try:
            episode = self.project.load_episode(self.current_episode_id)
        except FileNotFoundError:
            return

        episode.filename = self.filename

        # Parse result
        if self.parse_result:
            episode.parse_result_lines = list(self.parse_result.lines)
            episode.parse_result_metadata = dict(self.parse_result.metadata)
            episode.parse_result_line_metadata = dict(self.parse_result.line_metadata)
        else:
            episode.parse_result_lines = []
            episode.parse_result_metadata = {}
            episode.parse_result_line_metadata = {}

        # Scenes
        episode.scenes = []
        if self.scene_list:
            for s in self.scene_list:
                episode.scenes.append({
                    "scene_number": s.scene_number,
                    "heading": s.heading,
                    "location": s.location,
                    "time_of_day": s.time_of_day,
                    "int_ext": s.int_ext,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                    "content": s.content,
                    "summary": s.summary,
                    "scene_type": s.scene_type,
                    "is_manually_adjusted": s.is_manually_adjusted,
                    "confidence": s.confidence,
                })

        # Entities and analysis
        episode.entities = copy.deepcopy(self.entities)
        episode.global_entities = copy.deepcopy(self.global_entities)
        episode.character_analyses = copy.deepcopy(self.character_analyses)
        episode.global_analysis = self.global_analysis
        episode.synopsis = self.episode_synopsis

        # Undo/redo stacks
        episode.undo_stack = copy.deepcopy(self._undo_stack)
        episode.redo_stack = copy.deepcopy(self._redo_stack)

        self.project.save_episode(episode)

    def load_from_episode(self, episode_id: str) -> None:
        """Restore AppState from a saved EpisodeState."""
        if not self.project:
            return

        episode = self.project.load_episode(episode_id)
        self.current_episode_id = episode_id
        self.project.meta.active_episode_id = episode_id

        self.filename = episode.filename

        # Restore parse result
        if episode.parse_result_lines:
            self.parse_result = ParseResult(
                lines=episode.parse_result_lines,
                metadata=episode.parse_result_metadata,
                line_metadata=episode.parse_result_line_metadata,
            )
        else:
            self.parse_result = None

        # Restore scenes
        if episode.scenes:
            self._restore_snapshot({"scenes": episode.scenes})
        else:
            self.scene_list = None

        # Restore entities (normalize to int keys)
        self.entities = {}
        for k, v in episode.entities.items():
            self.entities[int(k) if isinstance(k, str) else k] = v

        self.global_entities = copy.deepcopy(episode.global_entities)
        self.character_analyses = copy.deepcopy(episode.character_analyses)
        self.global_analysis = episode.global_analysis
        self.episode_synopsis = episode.synopsis

        # Restore undo/redo stacks
        self._undo_stack = copy.deepcopy(episode.undo_stack)
        self._redo_stack = copy.deepcopy(episode.redo_stack)

        self.llm_task = LLMTask()
        self.status_message = f"已切换到: {episode.name}"

    # ── Serialization ───────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize full state to dict for the frontend."""
        data = {
            "filename": self.filename,
            "status": self.status_message,
            "content_locked": self.content_locked,
            "lines": [],
            "scenes": [],
            "can_undo": self.can_undo,
            "can_redo": self.can_redo,
            "entities": self.entities,
            "global_entities": self.global_entities,
            "character_analyses": self.character_analyses,
            "global_analysis": self.global_analysis,
            "episode_synopsis": self.episode_synopsis,
            "llm_config": {
                "provider": self.llm_config.provider,
                "model_name": self.llm_config.model_name,
                "api_key": "***" if self.llm_config.api_key else "",
                "base_url": self.llm_config.base_url,
                "temperature": self.llm_config.temperature,
                "max_tokens": self.llm_config.max_tokens,
            },
            "project": None,
        }

        if self.parse_result:
            data["lines"] = self.parse_result.lines

        if self.scene_list:
            data["scenes"] = [self._scene_to_dict(s) for s in self.scene_list]

        if self.project:
            data["project"] = {
                "id": self.project.meta.id,
                "name": self.project.meta.name,
                "active_episode_id": self.project.meta.active_episode_id,
                "episodes": self.project.get_episodes_info(),
            }

        data["schedule"] = self.schedule.to_dict() if self.schedule else None

        return data

    @staticmethod
    def _scene_to_dict(scene: Scene) -> dict:
        return {
            "scene_number": scene.scene_number,
            "heading": scene.heading,
            "location": scene.location,
            "time_of_day": scene.time_of_day,
            "int_ext": scene.int_ext,
            "start_line": scene.start_line,
            "end_line": scene.end_line,
            "summary": scene.summary,
            "scene_type": scene.scene_type,
            "is_manually_adjusted": scene.is_manually_adjusted,
            "confidence": scene.confidence,
            "line_count": scene.line_count(),
        }
