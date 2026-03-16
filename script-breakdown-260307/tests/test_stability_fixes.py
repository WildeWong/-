"""Regression tests for stability fixes."""
import sys
import types
import unittest

from src.llm.base import BaseLLM, LLMConfig
from src.parsers.base import ParseResult
from src.parsers.fdx_parser import FdxParser
from src.scene.llm_detector import LLMSceneDetector


class _FakeLLM(BaseLLM):
    def __init__(self, scene_dicts):
        super().__init__(LLMConfig())
        self._scene_dicts = scene_dicts

    def complete(self, prompt: str, system_prompt: str = "") -> str:
        return ""

    def detect_scenes(self, script_text: str) -> list[dict]:
        return list(self._scene_dicts)

    def test_connection(self) -> bool:
        return True

    def extract_heading_fields(self, scenes: list[dict]) -> list[dict]:
        return [{"int_ext": "", "location": "", "time_of_day": "", "scene_type": ""} for _ in scenes]


class TestLLMSceneDetectorNormalization(unittest.TestCase):

    def test_llm_detect_sorts_and_deduplicates_line_indexes(self):
        lines = [
            "INT. OFFICE - DAY",
            "John works.",
            "EXT. PARK - NIGHT",
            "Mary walks.",
        ]
        llm = _FakeLLM([
            {"line_index": "2", "heading": "EXT. PARK - NIGHT", "int_ext": "EXT", "location": "PARK", "time_of_day": "NIGHT"},
            {"line_index": 0, "heading": "INT. OFFICE - DAY", "int_ext": "INT", "location": "OFFICE", "time_of_day": "DAY"},
            {"line_index": 2, "heading": "", "int_ext": "", "location": "", "time_of_day": ""},
            {"line_index": "bad-index", "heading": "BROKEN"},
            {"line_index": 99, "heading": "OUT OF RANGE"},
            123,
        ])

        detector = LLMSceneDetector(llm)
        scenes = detector._llm_detect("\n".join(lines), lines)

        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0].start_line, 0)
        self.assertEqual(scenes[0].end_line, 2)
        self.assertEqual(scenes[1].start_line, 2)
        self.assertEqual(scenes[1].end_line, 4)
        self.assertEqual(scenes[0].location, "OFFICE")
        self.assertEqual(scenes[1].location, "PARK")

    def test_llm_detect_chunked_uses_same_normalization(self):
        lines = [
            "INT. OFFICE - DAY",
            "John works.",
            "EXT. PARK - NIGHT",
            "Mary walks.",
        ]
        llm = _FakeLLM([
            {"line_index": "2", "heading": "EXT. PARK - NIGHT", "int_ext": "EXT", "location": "PARK", "time_of_day": "NIGHT"},
            {"line_index": 0, "heading": "INT. OFFICE - DAY", "int_ext": "INT", "location": "OFFICE", "time_of_day": "DAY"},
            {"line_index": 0, "heading": "", "int_ext": "", "location": "", "time_of_day": ""},
        ])

        detector = LLMSceneDetector(llm)
        scenes = detector._llm_detect_chunked(lines)

        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0].start_line, 0)
        self.assertEqual(scenes[1].start_line, 2)


class TestFdxParserSafety(unittest.TestCase):

    def test_fdx_parser_disables_entity_resolution(self):
        parser_calls = {}

        class FakeXMLParser:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeRoot:
            def iter(self, tag):
                return []

            def find(self, path):
                return None

        class FakeTree:
            def getroot(self):
                return FakeRoot()

        class FakeEtree:
            XMLParser = FakeXMLParser

            @staticmethod
            def parse(file_path, parser=None):
                parser_calls["file_path"] = file_path
                parser_calls["parser"] = parser
                return FakeTree()

        fake_lxml = types.ModuleType("lxml")
        fake_lxml.etree = FakeEtree

        original_lxml = sys.modules.get("lxml")
        sys.modules["lxml"] = fake_lxml
        try:
            result = FdxParser().parse("sample.fdx")
        finally:
            if original_lxml is None:
                sys.modules.pop("lxml", None)
            else:
                sys.modules["lxml"] = original_lxml

        self.assertEqual(result, ParseResult(lines=[], metadata={}, line_metadata={}))
        self.assertIsInstance(parser_calls["parser"], FakeXMLParser)
        self.assertFalse(parser_calls["parser"].kwargs.get("resolve_entities", True))
        self.assertTrue(parser_calls["parser"].kwargs.get("no_network", False))


if __name__ == "__main__":
    unittest.main()
