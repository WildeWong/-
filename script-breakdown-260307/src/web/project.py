"""Project persistence: multi-episode script management."""
import copy
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..schedule.models import ProductionSchedule, ScheduleSnapshot
    from ..callsheet.models import CallSheet

PROJECTS_DIR = os.path.expanduser("~/.script-breakdown/projects")


# ── EpisodeState ─────────────────────────────────────────────────

@dataclass
class EpisodeState:
    """Complete state snapshot for a single episode."""
    id: str
    name: str
    filename: str
    order: int

    # Parse result
    parse_result_lines: list = field(default_factory=list)
    parse_result_metadata: dict = field(default_factory=dict)
    parse_result_line_metadata: dict = field(default_factory=dict)

    # Scene data (serialized scene dicts)
    scenes: list = field(default_factory=list)

    # Entity data
    entities: dict = field(default_factory=dict)
    global_entities: dict = field(default_factory=lambda: {"characters": [], "props": []})
    character_analyses: dict = field(default_factory=dict)
    global_analysis: str = ""

    # Episode synopsis (LLM-generated or user-written)
    synopsis: str = ""

    # Undo/redo stacks (each entry is a dict snapshot)
    undo_stack: list = field(default_factory=list)
    redo_stack: list = field(default_factory=list)

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "filename": self.filename,
            "order": self.order,
            "parse_result_lines": self.parse_result_lines,
            "parse_result_metadata": self.parse_result_metadata,
            "parse_result_line_metadata": {
                str(k): v for k, v in self.parse_result_line_metadata.items()
            },
            "scenes": self.scenes,
            "entities": {str(k): v for k, v in self.entities.items()},
            "global_entities": self.global_entities,
            "character_analyses": self.character_analyses,
            "global_analysis": self.global_analysis,
            "synopsis": self.synopsis,
            "undo_stack": self.undo_stack,
            "redo_stack": self.redo_stack,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EpisodeState":
        line_meta = {
            int(k): v
            for k, v in d.get("parse_result_line_metadata", {}).items()
        }
        entities = {
            int(k): v
            for k, v in d.get("entities", {}).items()
        }
        return cls(
            id=d["id"],
            name=d["name"],
            filename=d.get("filename", ""),
            order=d.get("order", 0),
            parse_result_lines=d.get("parse_result_lines", []),
            parse_result_metadata=d.get("parse_result_metadata", {}),
            parse_result_line_metadata=line_meta,
            scenes=d.get("scenes", []),
            entities=entities,
            global_entities=d.get("global_entities", {"characters": [], "props": []}),
            character_analyses=d.get("character_analyses", {}),
            global_analysis=d.get("global_analysis", ""),
            synopsis=d.get("synopsis", ""),
            undo_stack=d.get("undo_stack", []),
            redo_stack=d.get("redo_stack", []),
            created_at=d.get("created_at", datetime.now().isoformat()),
            updated_at=d.get("updated_at", datetime.now().isoformat()),
        )


# ── ProjectMeta ──────────────────────────────────────────────────

@dataclass
class ProjectMeta:
    """Project-level metadata."""
    id: str
    name: str
    llm_config: dict = field(default_factory=dict)
    episode_order: list = field(default_factory=list)   # ordered list of episode IDs
    active_episode_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "llm_config": self.llm_config,
            "episode_order": self.episode_order,
            "active_episode_id": self.active_episode_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectMeta":
        return cls(
            id=d["id"],
            name=d["name"],
            llm_config=d.get("llm_config", {}),
            episode_order=d.get("episode_order", []),
            active_episode_id=d.get("active_episode_id", ""),
            created_at=d.get("created_at", datetime.now().isoformat()),
            updated_at=d.get("updated_at", datetime.now().isoformat()),
        )


# ── Project ──────────────────────────────────────────────────────

class Project:
    """Manages a multi-episode project with JSON persistence."""

    def __init__(self, meta: ProjectMeta, project_dir: str):
        self.meta = meta
        self.project_dir = project_dir
        self._episodes: dict[str, EpisodeState] = {}  # in-memory cache

    # ── Class Methods ─────────────────────────────────────────────

    @classmethod
    def create_new(cls, name: str) -> "Project":
        """Create a new project with a unique ID."""
        project_id = str(uuid.uuid4())[:8]
        project_dir = os.path.join(PROJECTS_DIR, project_id)
        os.makedirs(project_dir, exist_ok=True)

        meta = ProjectMeta(id=project_id, name=name)
        project = cls(meta, project_dir)
        project._save_meta()
        return project

    @classmethod
    def load(cls, project_id: str) -> "Project":
        """Load an existing project by ID."""
        project_dir = os.path.join(PROJECTS_DIR, project_id)
        meta_path = os.path.join(project_dir, "project.json")

        if not os.path.exists(meta_path):
            raise FileNotFoundError(f"Project not found: {project_id}")

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = ProjectMeta.from_dict(json.load(f))

        return cls(meta, project_dir)

    @classmethod
    def list_projects(cls) -> list[dict]:
        """List all projects sorted by most recently updated."""
        if not os.path.exists(PROJECTS_DIR):
            return []

        projects = []
        for project_id in os.listdir(PROJECTS_DIR):
            meta_path = os.path.join(PROJECTS_DIR, project_id, "project.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    projects.append({
                        "id": meta["id"],
                        "name": meta["name"],
                        "created_at": meta.get("created_at", ""),
                        "updated_at": meta.get("updated_at", ""),
                        "episode_count": len(meta.get("episode_order", [])),
                    })
                except Exception:
                    pass

        projects.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
        return projects

    # ── Persistence ───────────────────────────────────────────────

    def _save_meta(self) -> None:
        self.meta.updated_at = datetime.now().isoformat()
        meta_path = os.path.join(self.project_dir, "project.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(self.meta.to_dict(), f, ensure_ascii=False, indent=2)

    def save_episode(self, episode: EpisodeState) -> None:
        """Save a single episode to disk and update the in-memory cache."""
        episode.updated_at = datetime.now().isoformat()
        episode_path = os.path.join(self.project_dir, f"episode_{episode.id}.json")
        with open(episode_path, "w", encoding="utf-8") as f:
            json.dump(episode.to_dict(), f, ensure_ascii=False, indent=2)
        self._episodes[episode.id] = episode

    def load_episode(self, episode_id: str) -> EpisodeState:
        """Load an episode from disk (uses in-memory cache)."""
        if episode_id in self._episodes:
            return self._episodes[episode_id]

        episode_path = os.path.join(self.project_dir, f"episode_{episode_id}.json")
        if not os.path.exists(episode_path):
            raise FileNotFoundError(f"Episode not found: {episode_id}")

        with open(episode_path, "r", encoding="utf-8") as f:
            episode = EpisodeState.from_dict(json.load(f))

        self._episodes[episode_id] = episode
        return episode

    def save(self) -> None:
        """Save all cached episodes and project metadata."""
        for episode in self._episodes.values():
            self.save_episode(episode)
        self._save_meta()

    def delete_project(self) -> None:
        """Delete the entire project directory."""
        import shutil
        if os.path.exists(self.project_dir):
            shutil.rmtree(self.project_dir)

    # ── Episode Management ─────────────────────────────────────────

    def add_episode(self, name: str, filename: str) -> EpisodeState:
        """Create a new empty episode and add it to the project."""
        episode_id = str(uuid.uuid4())[:8]
        order = len(self.meta.episode_order)
        episode = EpisodeState(id=episode_id, name=name, filename=filename, order=order)

        self.meta.episode_order.append(episode_id)
        if not self.meta.active_episode_id:
            self.meta.active_episode_id = episode_id

        self.save_episode(episode)
        self._save_meta()
        return episode

    def remove_episode(self, episode_id: str) -> None:
        """Remove an episode (cannot remove the last one)."""
        if len(self.meta.episode_order) <= 1:
            raise ValueError("不允许删除最后一集")

        if episode_id not in self.meta.episode_order:
            raise ValueError(f"集数不存在: {episode_id}")

        self.meta.episode_order.remove(episode_id)

        if self.meta.active_episode_id == episode_id:
            self.meta.active_episode_id = self.meta.episode_order[0]

        episode_path = os.path.join(self.project_dir, f"episode_{episode_id}.json")
        if os.path.exists(episode_path):
            os.remove(episode_path)

        self._episodes.pop(episode_id, None)

        # Reorder remaining episodes
        for i, eid in enumerate(self.meta.episode_order):
            try:
                ep = self.load_episode(eid)
                ep.order = i
                self.save_episode(ep)
            except Exception:
                pass

        self._save_meta()

    def rename_episode(self, episode_id: str, new_name: str) -> None:
        """Rename an episode."""
        episode = self.load_episode(episode_id)
        episode.name = new_name
        self.save_episode(episode)

    def reorder_episodes(self, new_order: list) -> None:
        """Reorder episodes by providing the new list of IDs."""
        if set(new_order) != set(self.meta.episode_order):
            raise ValueError("新排序必须包含相同的集数 ID")

        self.meta.episode_order = new_order
        for i, eid in enumerate(new_order):
            try:
                ep = self.load_episode(eid)
                ep.order = i
                self.save_episode(ep)
            except Exception:
                pass

        self._save_meta()

    # ── Schedule Persistence ───────────────────────────────────────

    def save_schedule(self, schedule: "ProductionSchedule") -> None:
        """Persist ProductionSchedule to schedule.json in the project directory."""
        path = os.path.join(self.project_dir, "schedule.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(schedule.to_dict(), f, ensure_ascii=False, indent=2)
        self._save_meta()

    def load_schedule(self) -> Optional["ProductionSchedule"]:
        """Load ProductionSchedule from disk. Returns None if file is absent or corrupt."""
        path = os.path.join(self.project_dir, "schedule.json")
        if not os.path.exists(path):
            return None
        try:
            from ..schedule.models import ProductionSchedule
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ProductionSchedule.from_dict(data)
        except Exception:
            return None

    def save_schedule_snapshot(self, snapshot: "ScheduleSnapshot") -> None:
        """Save a single ScheduleSnapshot to snapshots/schedule_v<N>.json."""
        snaps_dir = os.path.join(self.project_dir, "snapshots")
        os.makedirs(snaps_dir, exist_ok=True)
        path = os.path.join(snaps_dir, f"schedule_v{snapshot.version}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2)

    def list_schedule_snapshots(self) -> list[dict]:
        """Return snapshot metadata (version, timestamp, trigger, diff_summary) sorted by version."""
        snaps_dir = os.path.join(self.project_dir, "snapshots")
        if not os.path.exists(snaps_dir):
            return []
        result = []
        for fname in os.listdir(snaps_dir):
            if fname.startswith("schedule_v") and fname.endswith(".json"):
                fpath = os.path.join(snaps_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    result.append({
                        "version": d.get("version", 0),
                        "timestamp": d.get("timestamp", ""),
                        "trigger": d.get("trigger", ""),
                        "diff_summary": d.get("diff_summary", ""),
                    })
                except Exception:
                    pass
        result.sort(key=lambda x: x["version"])
        return result

    def load_schedule_snapshot(self, version: int) -> "ScheduleSnapshot":
        """Load a specific ScheduleSnapshot by version number.

        Raises FileNotFoundError if the snapshot does not exist.
        """
        snaps_dir = os.path.join(self.project_dir, "snapshots")
        path = os.path.join(snaps_dir, f"schedule_v{version}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"快照版本 {version} 不存在")
        from ..schedule.models import ScheduleSnapshot
        with open(path, "r", encoding="utf-8") as f:
            return ScheduleSnapshot.from_dict(json.load(f))

    # ── Callsheet Persistence ──────────────────────────────────────

    def save_callsheet(self, callsheet: "CallSheet") -> None:
        """Persist a CallSheet to callsheets/{date}.json."""
        cs_dir = os.path.join(self.project_dir, "callsheets")
        os.makedirs(cs_dir, exist_ok=True)
        path = os.path.join(cs_dir, f"{callsheet.date}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(callsheet.to_dict(), f, ensure_ascii=False, indent=2)

    def load_callsheet(self, date: str) -> "CallSheet":
        """Load a CallSheet by date string (YYYY-MM-DD).

        Raises FileNotFoundError if the file does not exist.
        """
        path = os.path.join(self.project_dir, "callsheets", f"{date}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"通告单不存在: {date}")
        from ..callsheet.models import CallSheet
        with open(path, "r", encoding="utf-8") as f:
            return CallSheet.from_dict(json.load(f))

    def list_callsheets(self) -> list[dict]:
        """Return summary metadata for all saved callsheets, sorted by date."""
        cs_dir = os.path.join(self.project_dir, "callsheets")
        if not os.path.exists(cs_dir):
            return []
        result = []
        for fname in os.listdir(cs_dir):
            if fname.endswith(".json"):
                fpath = os.path.join(cs_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    result.append({
                        "date": d.get("date", ""),
                        "day_number": d.get("day_number", 0),
                        "crew_call": d.get("crew_call", ""),
                        "location": d.get("location", ""),
                        "scene_count": len(d.get("scenes", [])),
                        "cast_count": len(d.get("cast", [])),
                    })
                except Exception:
                    pass
        result.sort(key=lambda x: x["date"])
        return result

    def get_episodes_info(self) -> list[dict]:
        """Get summary info for all episodes in order."""
        result = []
        for eid in self.meta.episode_order:
            try:
                ep = self.load_episode(eid)
                result.append({
                    "id": ep.id,
                    "name": ep.name,
                    "filename": ep.filename,
                    "order": ep.order,
                    "scene_count": len(ep.scenes),
                    "created_at": ep.created_at,
                    "updated_at": ep.updated_at,
                })
            except Exception:
                pass
        return result
