"""LLM-assisted scene detection, summarization, and entity analysis."""
from __future__ import annotations

from ..llm.base import BaseLLM
from ..parsers.base import ParseResult
from .detector import SceneDetector
from .entity_extractor import extract_entities as rule_extract_entities
from .models import Scene, SceneList
from .patterns import PatternMatch


class LLMSceneDetector:
    """Uses LLM to assist with scene detection and generate summaries."""

    # Max characters to send in a single LLM request
    MAX_CHUNK_SIZE = 12000

    def __init__(self, llm: BaseLLM):
        self.llm = llm
        self.rule_detector = SceneDetector()

    def detect(self, parse_result: ParseResult) -> SceneList:
        """Detect scenes combining rule-based and LLM detection.

        Strategy:
        1. Rule-based detection always runs first.
        2. If rule detection is low-confidence or missing location fields, LLM re-detects boundaries.
        3. LLM enrichment (heading fields + scene_type) always runs on the final scene list.
        """
        rule_result = self.rule_detector.detect(parse_result)
        lines = parse_result.lines

        low_confidence = [s for s in rule_result if s.confidence < 0.7]
        missing_location = [s for s in rule_result if not s.location and not s.int_ext]

        # Decide which scene list to use as the base
        if not low_confidence and not missing_location and len(rule_result) > 1:
            final = rule_result
        else:
            # Use LLM for boundary detection when rule result is weak
            script_text = "\n".join(lines)
            llm_scenes = self._llm_detect(script_text, lines)
            final = llm_scenes if (llm_scenes and len(llm_scenes) >= len(rule_result)) else rule_result

        # Always enrich: fill missing heading fields AND infer scene_type via LLM
        self._enrich_scenes(final)
        return final

    def _enrich_scenes(self, scene_list: SceneList) -> None:
        """Enrich all scenes that are missing any of: location, int_ext, or scene_type.

        Sends heading + scene content to LLM in batches of 5.
        Also populates scene_type (场景类别) for every scene that lacks it.
        """
        needs = [
            (i, s) for i, s in enumerate(scene_list)
            if not s.location or not s.int_ext or not s.scene_type
        ]
        if not needs:
            return

        batch_size = 5
        for batch_start in range(0, len(needs), batch_size):
            batch = needs[batch_start:batch_start + batch_size]
            scene_dicts = [{"heading": s.heading, "content": s.content} for _, s in batch]
            try:
                enriched = self.llm.extract_heading_fields(scene_dicts)
            except Exception:
                continue
            for (_, scene), fields in zip(batch, enriched):
                if not scene.location and fields.get("location"):
                    scene.location = fields["location"]
                if not scene.int_ext and fields.get("int_ext"):
                    scene.int_ext = fields["int_ext"]
                if not scene.time_of_day and fields.get("time_of_day"):
                    scene.time_of_day = fields["time_of_day"]
                if not scene.scene_type and fields.get("scene_type"):
                    scene.scene_type = fields["scene_type"]

    def summarize_scenes(self, scene_list: SceneList) -> None:
        """Generate summaries for all scenes in place."""
        for scene in scene_list:
            if not scene.summary and scene.content.strip():
                try:
                    scene.summary = self.llm.summarize_scene(scene.content)
                except Exception:
                    scene.summary = "(Summary generation failed)"

    def summarize_single_scene(self, scene: Scene) -> str:
        """Generate summary for a single scene."""
        if not scene.content.strip():
            return ""
        try:
            summary = self.llm.summarize_scene(scene.content)
            scene.summary = summary
            return summary
        except Exception as e:
            return f"(Error: {e})"

    def _llm_detect(self, script_text: str, lines: list[str]) -> SceneList:
        """Use LLM to detect scenes."""
        # Split into chunks if too large
        if len(script_text) > self.MAX_CHUNK_SIZE:
            return self._llm_detect_chunked(lines)

        try:
            scene_dicts = self.llm.detect_scenes(script_text)
        except Exception:
            return SceneList()

        if not scene_dicts:
            return SceneList()

        scene_dicts = self._normalize_scene_dicts(scene_dicts, len(lines))
        if not scene_dicts:
            return SceneList()

        scenes: list[Scene] = []
        total_lines = len(lines)

        for i, sd in enumerate(scene_dicts):
            line_idx = sd.get("line_index", 0)
            if line_idx < 0 or line_idx >= total_lines:
                continue
            end_line = (
                scene_dicts[i + 1].get("line_index", total_lines)
                if i + 1 < len(scene_dicts)
                else total_lines
            )
            end_line = min(end_line, total_lines)

            scene = Scene(
                scene_number=i + 1,
                heading=sd.get("heading", lines[line_idx].strip()),
                location=sd.get("location", ""),
                time_of_day=sd.get("time_of_day", ""),
                int_ext=sd.get("int_ext", ""),
                start_line=line_idx,
                end_line=end_line,
                content="\n".join(lines[line_idx:end_line]),
                confidence=0.85,
            )
            scenes.append(scene)

        return SceneList(scenes)

    # ── Entity extraction ──────────────────────────────────────

    def extract_entities(self, scene: Scene, scene_type_keys: list | None = None) -> dict:
        """Extract entities from a scene using rules + LLM hybrid approach.

        Args:
            scene: The scene to extract entities from.
            scene_type_keys: Optional list of valid scene_type_key values (e.g. ["A1_简单对话", ...]).
                             If provided, LLM will also classify the scene into one of these keys.

        Returns:
            {"characters": [...], "props": [...], "scene_type": "", "scene_type_key": ""}
        """
        # 1. Rule-based extraction first
        rule_result = rule_extract_entities(scene)

        # 2. LLM extraction
        try:
            llm_result = self.llm.extract_entities(scene.content)
        except Exception:
            llm_result = {"characters": [], "props": [], "scene_type": ""}

        # 3. Merge and deduplicate
        characters = list(dict.fromkeys(
            rule_result["characters"] + llm_result.get("characters", [])
        ))
        props = list(dict.fromkeys(
            rule_result["props"] + llm_result.get("props", [])
        ))
        scene_type = llm_result.get("scene_type", "") or rule_result.get("scene_type", "")

        result = {
            "characters": characters,
            "props": props,
            "scene_type": scene_type,
            "scene_type_key": "",
        }

        # 4. 若提供了场景类型键列表，使用 LLM 进行结构化分类
        if scene_type_keys:
            try:
                type_list = "\n".join(f"  - {k}" for k in scene_type_keys)
                chars_str = "、".join(characters[:5]) if characters else "无"
                prompt = (
                    f"你是影视制片助手，请将以下场次归类到场景类型。\n"
                    f"可选类型（只能选一个key，原样返回）：\n{type_list}\n\n"
                    f"场次标题: {getattr(scene, 'heading', '')}\n"
                    f"角色: {chars_str}\n"
                    f"内容摘要: {(getattr(scene, 'summary', '') or scene.content[:200])}\n\n"
                    f"只返回类型key，如: A7_武戏"
                )
                raw = self.llm.complete(prompt).strip()
                for tk in scene_type_keys:
                    if tk in raw:
                        result["scene_type_key"] = tk
                        break
            except Exception:
                pass

        return result

    def extract_entities_rules_only(self, scene: Scene) -> dict:
        """Extract entities using rules only (no LLM)."""
        return rule_extract_entities(scene)

    # ── Character analysis ─────────────────────────────────────

    def analyze_character(self, character_name: str, relevant_scenes: list[Scene]) -> str:
        """Analyze a single character across their relevant scenes."""
        scenes_text = "\n\n---\n\n".join(
            f"[Scene {s.scene_number}: {s.heading}]\n{s.content}"
            for s in relevant_scenes
            if s.content.strip()
        )
        if not scenes_text:
            return ""
        try:
            return self.llm.analyze_character(character_name, scenes_text)
        except Exception as e:
            return f"(Analysis failed: {e})"

    def analyze_characters_global(self, scene_list: SceneList, character_names: list[str]) -> str:
        """Analyze all characters and their relationships globally."""
        # Build a condensed script representation
        parts = []
        for scene in scene_list:
            if scene.content.strip():
                parts.append(f"[Scene {scene.scene_number}: {scene.heading}]\n{scene.content}")
        script_text = "\n\n---\n\n".join(parts)
        try:
            return self.llm.analyze_all_characters(script_text, character_names)
        except Exception as e:
            return f"(Global analysis failed: {e})"

    def _llm_detect_chunked(self, lines: list[str]) -> SceneList:
        """Detect scenes in large scripts by processing in chunks."""
        chunk_size = 200  # lines per chunk
        all_scene_dicts: list[dict] = []

        for start in range(0, len(lines), chunk_size):
            end = min(start + chunk_size, len(lines))
            chunk_text = "\n".join(lines[start:end])
            try:
                chunk_scenes = self._normalize_scene_dicts(
                    self.llm.detect_scenes(chunk_text),
                    end - start,
                )
                # Adjust line indices to global after local normalization.
                for sd in chunk_scenes:
                    adjusted = dict(sd)
                    adjusted["line_index"] = adjusted["line_index"] + start
                    all_scene_dicts.append(adjusted)
            except Exception:
                continue

        if not all_scene_dicts:
            return SceneList()

        total_lines = len(lines)
        all_scene_dicts = self._normalize_scene_dicts(all_scene_dicts, total_lines)
        if not all_scene_dicts:
            return SceneList()

        scenes: list[Scene] = []
        for i, sd in enumerate(all_scene_dicts):
            line_idx = sd.get("line_index", 0)
            end_line = (
                all_scene_dicts[i + 1].get("line_index", total_lines)
                if i + 1 < len(all_scene_dicts)
                else total_lines
            )
            scenes.append(Scene(
                scene_number=i + 1,
                heading=sd.get("heading", lines[line_idx].strip() if line_idx < total_lines else ""),
                location=sd.get("location", ""),
                time_of_day=sd.get("time_of_day", ""),
                int_ext=sd.get("int_ext", ""),
                start_line=line_idx,
                end_line=min(end_line, total_lines),
                content="\n".join(lines[line_idx:min(end_line, total_lines)]),
                confidence=0.80,
            ))

        return SceneList(scenes)

    def _normalize_scene_dicts(self, scene_dicts: list[dict], total_lines: int) -> list[dict]:
        """Normalize LLM scene output into a sorted, deduplicated list.

        LLMs occasionally return non-dict items, duplicate line indexes, strings for
        numeric indexes, or out-of-order results. This keeps downstream scene slicing
        stable and prevents zero-length / overlapping scenes.
        """
        normalized_by_index: dict[int, dict] = {}

        for raw in scene_dicts:
            if not isinstance(raw, dict):
                continue

            try:
                line_idx = int(raw.get("line_index", -1))
            except (TypeError, ValueError):
                continue

            if line_idx < 0 or line_idx >= total_lines:
                continue

            current = normalized_by_index.get(line_idx)
            candidate = {
                "line_index": line_idx,
                "heading": str(raw.get("heading", "") or "").strip(),
                "location": str(raw.get("location", "") or "").strip(),
                "time_of_day": str(raw.get("time_of_day", "") or "").strip(),
                "int_ext": str(raw.get("int_ext", "") or "").strip(),
            }

            if current is None:
                normalized_by_index[line_idx] = candidate
                continue

            for key in ("heading", "location", "time_of_day", "int_ext"):
                if not current[key] and candidate[key]:
                    current[key] = candidate[key]

        return [normalized_by_index[idx] for idx in sorted(normalized_by_index)]
