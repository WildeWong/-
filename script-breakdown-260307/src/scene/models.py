from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Scene:
    """Represents a single scene in a screenplay."""
    scene_number: int
    heading: str                        # e.g. "INT. 医院走廊 - 日"
    location: str = ""                  # e.g. "医院走廊"
    time_of_day: str = ""               # e.g. "日", "夜", "DAY", "NIGHT"
    int_ext: str = ""                   # "INT", "EXT", "INT/EXT", "内", "外", "内外"
    start_line: int = 0                 # starting line index in script text
    end_line: int = 0                   # ending line index (exclusive)
    content: str = ""                   # full text content of this scene
    summary: str = ""                   # LLM-generated summary
    scene_type: str = ""                # user-assigned category (对话/动作/情感/etc.)
    is_manually_adjusted: bool = False  # whether user has manually calibrated
    confidence: float = 1.0             # detection confidence (0.0 - 1.0)
    estimated_duration: float = 0.0     # 预估拍摄时长（小时），由 duration_engine 填充
    duration_detail: dict = field(default_factory=dict)  # 时长分解详情

    def line_count(self) -> int:
        return self.end_line - self.start_line


class SceneList:
    """Manages an ordered collection of scenes with manipulation operations."""

    def __init__(self, scenes: Optional[list[Scene]] = None):
        self._scenes: list[Scene] = scenes or []

    @property
    def scenes(self) -> list[Scene]:
        return self._scenes

    def __len__(self) -> int:
        return len(self._scenes)

    def __getitem__(self, index: int) -> Scene:
        return self._scenes[index]

    def __iter__(self):
        return iter(self._scenes)

    def add_scene(self, scene: Scene) -> None:
        self._scenes.append(scene)
        self._scenes.sort(key=lambda s: s.start_line)
        self._renumber()

    def remove_scene(self, index: int) -> None:
        """Remove scene at index and merge its content into the previous scene."""
        if 0 <= index < len(self._scenes):
            removed = self._scenes.pop(index)
            # Merge content into previous scene if exists
            if index > 0 and index <= len(self._scenes):
                prev = self._scenes[index - 1]
                prev.end_line = removed.end_line
                prev.content = prev.content + "\n" + removed.content
            elif self._scenes:
                # Removed first scene, extend next scene backward
                self._scenes[0].start_line = removed.start_line
                self._scenes[0].content = removed.content + "\n" + self._scenes[0].content
            self._renumber()

    def batch_remove_scenes(self, indices: list[int]) -> dict:
        """Remove multiple scenes by index, merging content into adjacent scenes.

        Processes in descending order to avoid index shifting.
        Returns old_index -> new_index mapping for surviving scenes.
        """
        total = len(self._scenes)
        to_remove = set(i for i in indices if 0 <= i < total)

        if not to_remove or len(to_remove) >= total:
            return {}

        # Build old_to_new mapping for surviving scenes before any removal
        old_to_new: dict[int, int] = {}
        new_idx = 0
        for old_idx in range(total):
            if old_idx not in to_remove:
                old_to_new[old_idx] = new_idx
                new_idx += 1

        # Remove in descending order so lower indices remain stable
        for idx in sorted(to_remove, reverse=True):
            self.remove_scene(idx)

        return old_to_new

    def merge_scenes(self, index1: int, index2: int) -> None:
        """Merge two adjacent scenes into one."""
        lo, hi = min(index1, index2), max(index1, index2)
        if lo < 0 or hi >= len(self._scenes) or hi - lo != 1:
            return
        scene_a = self._scenes[lo]
        scene_b = self._scenes[hi]
        scene_a.end_line = scene_b.end_line
        scene_a.content = scene_a.content + "\n" + scene_b.content
        scene_a.is_manually_adjusted = True
        self._scenes.pop(hi)
        self._renumber()

    def insert_break(self, line_index: int, lines: list[str]) -> None:
        """Insert a scene break at the given line index, splitting the scene."""
        target_idx = self._find_scene_at_line(line_index)
        if target_idx is None:
            return
        target = self._scenes[target_idx]
        if line_index <= target.start_line or line_index >= target.end_line:
            return

        # Create new scene from the split point onward
        new_heading = lines[line_index].strip() if line_index < len(lines) else ""
        new_scene = Scene(
            scene_number=0,
            heading=new_heading,
            start_line=line_index,
            end_line=target.end_line,
            content="\n".join(lines[line_index:target.end_line]),
            is_manually_adjusted=True,
        )

        # Truncate original scene
        target.end_line = line_index
        target.content = "\n".join(lines[target.start_line:line_index])
        target.is_manually_adjusted = True

        self._scenes.insert(target_idx + 1, new_scene)
        self._renumber()

    def move_break(self, scene_index: int, new_start_line: int, lines: list[str]) -> None:
        """Move the start boundary of a scene to a new line."""
        if scene_index <= 0 or scene_index >= len(self._scenes):
            return
        current = self._scenes[scene_index]
        prev = self._scenes[scene_index - 1]

        if new_start_line <= prev.start_line or new_start_line >= current.end_line:
            return

        prev.end_line = new_start_line
        prev.content = "\n".join(lines[prev.start_line:new_start_line])
        prev.is_manually_adjusted = True

        current.start_line = new_start_line
        current.heading = lines[new_start_line].strip() if new_start_line < len(lines) else ""
        current.content = "\n".join(lines[new_start_line:current.end_line])
        current.is_manually_adjusted = True

    def delete_lines(self, line_indices: list[int], all_lines: list[str]) -> list[str]:
        """Delete specific lines from the script, updating scene boundaries.

        Returns the new list of lines after deletion.
        """
        if not line_indices:
            return list(all_lines)

        delete_set = set(line_indices)

        # Build old_idx -> new_idx mapping for surviving lines
        old_to_new: dict[int, int] = {}
        new_lines: list[str] = []
        new_idx = 0
        for old_idx, line in enumerate(all_lines):
            if old_idx not in delete_set:
                old_to_new[old_idx] = new_idx
                new_lines.append(line)
                new_idx += 1

        # Update each scene's boundaries
        for scene in self._scenes:
            old_start = scene.start_line
            old_end = scene.end_line

            # New start: first surviving line at or after old_start
            new_start = None
            for li in range(old_start, min(old_end, len(all_lines))):
                if li in old_to_new:
                    new_start = old_to_new[li]
                    break

            # New end: new_idx of last surviving line before old_end, +1
            new_end = None
            for li in range(min(old_end - 1, len(all_lines) - 1), old_start - 1, -1):
                if li in old_to_new:
                    new_end = old_to_new[li] + 1
                    break

            if new_start is None:
                # All lines in this scene were deleted — mark for removal
                scene.start_line = -1
                scene.end_line = -1
            else:
                scene.start_line = new_start
                scene.end_line = new_end if (new_end is not None and new_end > new_start) else new_start
                # If the heading line was deleted, update heading from new start line
                if old_start in delete_set and new_start < len(new_lines):
                    scene.heading = new_lines[new_start].strip()
                scene.is_manually_adjusted = True

        # Remove scenes that have no lines left
        self._scenes = [s for s in self._scenes if s.start_line != -1 and s.end_line > s.start_line]

        # Ensure the first scene starts at 0 (lines before first scene become part of it)
        if self._scenes and self._scenes[0].start_line > 0:
            self._scenes[0].start_line = 0

        # Rebuild contiguous coverage (no gaps between scenes)
        for i in range(1, len(self._scenes)):
            if self._scenes[i].start_line < self._scenes[i - 1].end_line:
                self._scenes[i].start_line = self._scenes[i - 1].end_line

        # Refresh content for all scenes
        for scene in self._scenes:
            scene.content = "\n".join(new_lines[scene.start_line:scene.end_line])

        self._renumber()
        return new_lines

    def _find_scene_at_line(self, line_index: int) -> Optional[int]:
        for i, scene in enumerate(self._scenes):
            if scene.start_line <= line_index < scene.end_line:
                return i
        return None

    def _renumber(self) -> None:
        for i, scene in enumerate(self._scenes):
            scene.scene_number = i + 1
