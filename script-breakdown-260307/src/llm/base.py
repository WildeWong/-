"""Abstract base class for LLM adapters."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    """Configuration for an LLM adapter."""
    provider: str = ""          # "claude", "openai", "ollama"
    model_name: str = ""        # e.g. "claude-sonnet-4-5-20250929", "gpt-4o", "llama3"
    api_key: str = ""
    base_url: str = ""          # For Ollama: "http://localhost:11434"
    temperature: float = 0.3
    max_tokens: int = 4096


class BaseLLM(ABC):
    """Abstract interface for LLM providers."""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    def complete(self, prompt: str, system_prompt: str = "") -> str:
        """Send a completion request to the LLM.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system prompt.

        Returns:
            The LLM's text response.
        """
        ...

    def detect_scenes(self, script_text: str) -> list[dict]:
        """Ask the LLM to identify scene boundaries in script text.

        Args:
            script_text: The full script text.

        Returns:
            List of dicts with keys: line_index, heading, int_ext, location, time_of_day
        """
        system_prompt = (
            "You are a professional screenplay analyst. "
            "Identify all scene boundaries in the given screenplay text. "
            "For each scene, provide the line number (0-indexed) where it starts, "
            "the scene heading, interior/exterior designation, location, and time of day. "
            "IMPORTANT: Scene headings may be bare numbers like '2-10'. "
            "In that case read the lines IMMEDIATELY AFTER the heading to find "
            "int_ext (内/外 or INT/EXT), location, and time of day — "
            "Chinese TV scripts often place this info on the line(s) after the scene number. "
            "Respond in JSON format as a list of objects with keys: "
            "line_index, heading, int_ext, location, time_of_day. "
            "Only output the JSON array, no other text."
        )

        # Add line numbers to help LLM reference specific lines
        numbered_lines = []
        for i, line in enumerate(script_text.splitlines()):
            numbered_lines.append(f"[{i}] {line}")
        numbered_text = "\n".join(numbered_lines)

        prompt = f"Identify all scene boundaries in this screenplay:\n\n{numbered_text}"
        response = self.complete(prompt, system_prompt)
        return self._parse_scene_json(response)

    def summarize_scene(self, scene_text: str) -> str:
        """Generate a concise summary for a scene.

        Args:
            scene_text: The text content of a single scene.

        Returns:
            A short summary string.
        """
        system_prompt = (
            "You are a professional screenplay analyst. "
            "Provide a concise summary (1-3 sentences) of the following scene. "
            "Focus on key actions, character interactions, and dramatic purpose. "
            "If the scene is in Chinese, respond in Chinese. "
            "If in English, respond in English."
        )
        prompt = f"Summarize this scene:\n\n{scene_text}"
        return self.complete(prompt, system_prompt).strip()

    def extract_entities(self, scene_text: str) -> dict:
        """Ask the LLM to extract entities (characters, props, scene type) from a scene.

        Args:
            scene_text: The text content of a single scene.

        Returns:
            Dict with keys: characters (list[str]), props (list[str]), scene_type (str)
        """
        system_prompt = (
            "You are a professional screenplay analyst.\n"
            "From the given scene, extract EXACTLY three things:\n\n"
            "1. characters — ONLY real character/person names who speak, act, or are explicitly described.\n"
            "   Rules:\n"
            "   - Include Chinese names (e.g. 张三, 李四), English names (e.g. JOHN, Mary), and mixed names.\n"
            "   - Include names followed by parentheticals like '张三（激动）' — the name is '张三'.\n"
            "   - Do NOT include: scene directions, locations, time markers, camera notes.\n"
            "   - Do NOT include: 旁白, V.O., O.S., INT, EXT, CUT TO, FADE, DAY, NIGHT, etc.\n"
            "   - Do NOT include: generic roles without names (e.g. '男人', '路人甲' unless these are\n"
            "     the only identifier used consistently throughout the scene).\n\n"
            "2. props — physical objects characters interact with that matter to the scene.\n\n"
            "3. scene_type — choose ONE from:\n"
            "   Chinese scripts: 对话 | 情感 | 动作 | 打斗 | 追逐 | 特效 | 过场 | 群戏 | 独白\n"
            "   English scripts: dialogue | action | chase | fight | transition | montage | crowd | monologue\n\n"
            "Respond ONLY in valid JSON:\n"
            '{"characters": ["name1", "name2"], "props": ["item1", "item2"], "scene_type": "..."}\n'
            "No explanations, no markdown, just the JSON object."
        )
        prompt = f"Extract entities from this scene:\n\n{scene_text}"
        response = self.complete(prompt, system_prompt)
        result = self._parse_entity_json(response)
        return result

    def extract_heading_fields(self, scenes: list[dict]) -> list[dict]:
        """Extract int_ext, location, time_of_day for scenes with missing heading fields.

        Args:
            scenes: List of dicts with 'heading' and 'content' keys.

        Returns:
            List of dicts with keys: int_ext, location, time_of_day (same order as input).
        """
        system_prompt = (
            "You are a professional screenplay analyst. "
            "For each scene below, extract four fields from the heading AND content:\n"
            "1. int_ext — interior/exterior: '内' or '外' (Chinese), 'INT' or 'EXT' (English), or ''.\n"
            "2. location — the scene location. If the heading has multiple place words like "
            "'唐楼 街头', keep them all joined by a space as a single location string.\n"
            "3. time_of_day — '日', '夜', '黄昏', '清晨' etc. (Chinese) or 'DAY', 'NIGHT' (English), or ''.\n"
            "4. scene_type — classify the scene from its CONTENT (not just the heading):\n"
            "   Chinese: 对话 | 情感 | 动作 | 打斗 | 追逐 | 特效 | 过场 | 群戏 | 独白\n"
            "   English: dialogue | action | chase | fight | transition | montage | crowd | monologue\n"
            "   '过场' (transition) means a very short scene used purely to show movement or passage of time.\n"
            "The heading may be a bare scene number. In that case read the FULL CONTENT — "
            "location, int_ext and time typically appear in the first few lines after the heading.\n"
            "If a field cannot be determined, use an empty string.\n"
            "Respond ONLY as a JSON array, one object per scene, "
            "keys: int_ext, location, time_of_day, scene_type. No other text."
        )

        scene_texts = []
        for i, scene in enumerate(scenes):
            heading = scene.get("heading", "")
            # Use more content so the LLM can read past the bare heading line
            content = scene.get("content", "")[:600]
            scene_texts.append(
                f"Scene {i + 1}:\n"
                f"[Heading]: {heading!r}\n"
                f"[Content]:\n{content}"
            )

        prompt = (
            "Extract int_ext, location, and time_of_day for each scene:\n\n"
            + "\n\n---\n\n".join(scene_texts)
        )

        try:
            response = self.complete(prompt, system_prompt)
            result = self._parse_scene_json(response)
            if isinstance(result, list) and result:
                # Best-effort positional mapping — LLM may return fewer items
                output = [{"int_ext": "", "location": "", "time_of_day": "", "scene_type": ""} for _ in scenes]
                for i, fields in enumerate(result):
                    if i < len(output) and isinstance(fields, dict):
                        output[i] = fields
                return output
        except Exception:
            pass
        return [{"int_ext": "", "location": "", "time_of_day": "", "scene_type": ""} for _ in scenes]

    def identify_scene_headings(self, lines: list[str], line_offset: int = 0) -> list[dict]:
        """Ask the LLM to identify scene headings in a chunk of text lines.

        Args:
            lines: Lines of script text (already extracted from PDF).
            line_offset: Global line index offset for this chunk.

        Returns:
            List of dicts with keys: line_index (global int), int_ext, location, time_of_day.
        """
        system_prompt = (
            "You are a professional screenplay analyst. "
            "Identify all scene headings in the given screenplay lines. "
            "For each scene heading, provide: "
            "- line_index: the integer line number shown in brackets [N] "
            "- int_ext: '内' or '外' (Chinese), 'INT' or 'EXT' (English), or empty string "
            "- location: the scene location name (e.g. '高龙城银行', 'POLICE STATION') "
            "- time_of_day: '日', '夜', '黄昏' etc. (Chinese) or 'DAY', 'NIGHT' (English), or empty string "
            "Scene headings in Chinese TV scripts often look like: "
            "'2-10.' on one line, then '高龙城银行外日' on the NEXT line (location+int_ext+time merged). "
            "Or: '2-9.阿瓦隆公路边境检查站机场外日' (all on one line). "
            "When a bare scene number like '2-10.' is followed by a compact location line, "
            "use the NEXT line's content for int_ext, location, time_of_day. "
            "Standard English format: 'INT. LOCATION - DAY' or 'EXT. LOCATION - NIGHT'. "
            "Respond ONLY as a JSON array. "
            "Keys: line_index (integer), int_ext (string), location (string), time_of_day (string). "
            "No other text, no markdown."
        )

        numbered = [f"[{line_offset + i}] {line}" for i, line in enumerate(lines)]
        prompt = "Identify scene headings in these screenplay lines:\n\n" + "\n".join(numbered)

        try:
            response = self.complete(prompt, system_prompt)
            result = self._parse_scene_json(response)
            if isinstance(result, list):
                return result
        except Exception:
            pass
        return []

    def analyze_character(self, character_name: str, scenes_text: str) -> str:
        """Analyze a character's role, personality, and arc across relevant scenes.

        Args:
            character_name: The character to analyze.
            scenes_text: Combined text of scenes where this character appears.

        Returns:
            Analysis text.
        """
        system_prompt = (
            "You are a professional screenplay analyst. "
            "Analyze the given character based on their appearances in the provided scenes. "
            "Cover: character traits, relationships, emotional arc, dramatic function, and key moments. "
            "If the text is in Chinese, respond in Chinese. If in English, respond in English. "
            "Keep the analysis concise but insightful (3-5 paragraphs)."
        )
        prompt = (
            f"Analyze the character \"{character_name}\" based on these scenes:\n\n"
            f"{scenes_text}"
        )
        return self.complete(prompt, system_prompt).strip()

    def analyze_all_characters(self, script_text: str, character_names: list[str]) -> dict:
        """Analyze all characters and their relationships globally.

        Args:
            script_text: The full script text (or summary).
            character_names: List of character names to analyze.

        Returns:
            Dict with 'relationships' (str) and per-character summaries.
        """
        names_str = ", ".join(character_names)
        system_prompt = (
            "You are a professional screenplay analyst. "
            "Provide a global analysis of the characters and their relationships. "
            "Cover: main conflicts, alliances, character dynamics, and thematic roles. "
            "If the text is in Chinese, respond in Chinese. If in English, respond in English."
        )
        prompt = (
            f"Characters: {names_str}\n\n"
            f"Analyze the relationships and dynamics between these characters "
            f"based on the following script:\n\n{script_text[:8000]}"
        )
        return self.complete(prompt, system_prompt).strip()

    @abstractmethod
    def test_connection(self) -> bool:
        """Test whether the LLM connection is working.

        Returns:
            True if connection is successful.
        """
        ...

    def _parse_entity_json(self, response: str) -> dict:
        """Parse JSON entity dict from LLM response."""
        import json
        text = response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {
                    "characters": data.get("characters", []),
                    "props": data.get("props", []),
                    "scene_type": data.get("scene_type", ""),
                }
        except json.JSONDecodeError:
            pass
        return {"characters": [], "props": [], "scene_type": ""}

    def _parse_scene_json(self, response: str) -> list[dict]:
        """Parse JSON scene list from LLM response."""
        import json
        # Try to extract JSON from response
        text = response.strip()
        # Remove markdown code fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        return []
