"""Tests for scene detection."""
import unittest

from src.parsers.base import ParseResult
from src.scene.detector import SceneDetector
from src.scene.patterns import (
    match_chinese_patterns, match_english_patterns, match_all_patterns,
)


class TestChinesePatterns(unittest.TestCase):

    def test_numbered_scene(self):
        m = match_chinese_patterns("第1场 内 医院走廊 - 日", 0)
        self.assertIsNotNone(m)
        self.assertEqual(m.pattern_name, "CH_SCENE_NUMBERED")

    def test_chinese_number_scene(self):
        m = match_chinese_patterns("第三场 外 街道 - 夜", 5)
        self.assertIsNotNone(m)
        self.assertEqual(m.line_index, 5)

    def test_scene_label(self):
        m = match_chinese_patterns("场景2：内 办公室 - 日", 0)
        self.assertIsNotNone(m)
        self.assertEqual(m.pattern_name, "CH_SCENE_LABEL")

    def test_numbered_int_ext(self):
        m = match_chinese_patterns("1. 内 医院走廊 - 日", 0)
        self.assertIsNotNone(m)
        self.assertEqual(m.int_ext, "内")
        self.assertEqual(m.location, "医院走廊")
        self.assertEqual(m.time_of_day, "日")

    def test_numbered_slash(self):
        m = match_chinese_patterns("1. 医院/走廊/日", 0)
        self.assertIsNotNone(m)
        self.assertEqual(m.time_of_day, "日")
        self.assertIn("医院", m.location)

    def test_bracketed(self):
        m = match_chinese_patterns("【第5场】内 学校 - 晨", 0)
        self.assertIsNotNone(m)
        self.assertEqual(m.pattern_name, "CH_BRACKETED")

    def test_int_ext_only(self):
        m = match_chinese_patterns("内 客厅 - 夜", 0)
        self.assertIsNotNone(m)
        self.assertEqual(m.int_ext, "内")
        self.assertEqual(m.location, "客厅")

    def test_no_match(self):
        m = match_chinese_patterns("这是一段普通的对话。", 0)
        self.assertIsNone(m)


class TestEnglishPatterns(unittest.TestCase):

    def test_int_scene(self):
        m = match_english_patterns("INT. HOSPITAL CORRIDOR - DAY", 0)
        self.assertIsNotNone(m)
        self.assertEqual(m.int_ext, "INT")
        self.assertEqual(m.location, "HOSPITAL CORRIDOR")
        self.assertEqual(m.time_of_day, "DAY")

    def test_ext_scene(self):
        m = match_english_patterns("EXT. CITY STREET - NIGHT", 3)
        self.assertIsNotNone(m)
        self.assertEqual(m.int_ext, "EXT")
        self.assertEqual(m.line_index, 3)

    def test_int_ext_scene(self):
        m = match_english_patterns("INT./EXT. CAR - DAY", 0)
        self.assertIsNotNone(m)
        self.assertEqual(m.int_ext, "INT./EXT")

    def test_numbered_scene(self):
        m = match_english_patterns("5. INT. OFFICE - DAY", 0)
        self.assertIsNotNone(m)

    def test_no_time(self):
        m = match_english_patterns("INT. OFFICE", 0)
        self.assertIsNotNone(m)
        self.assertEqual(m.time_of_day, "")

    def test_no_match(self):
        m = match_english_patterns("JOHN walks into the room.", 0)
        self.assertIsNone(m)


class TestSceneDetector(unittest.TestCase):

    def _make_result(self, lines):
        return ParseResult(lines=lines)

    def test_chinese_script(self):
        lines = [
            "剧本标题",
            "编剧：某某",
            "",
            "第1场 内 医院走廊 - 日",
            "医生匆忙地走过走廊。",
            "护士跟在后面。",
            "",
            "第2场 外 街道 - 夜",
            "行人稀少的街道上。",
            "主角独自行走。",
        ]
        detector = SceneDetector()
        result = detector.detect(self._make_result(lines))

        # Should have preamble + 2 scenes = 3
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1].heading, "第1场 内 医院走廊 - 日")
        self.assertEqual(result[2].heading, "第2场 外 街道 - 夜")

    def test_english_script(self):
        lines = [
            "FADE IN:",
            "",
            "INT. HOSPITAL CORRIDOR - DAY",
            "A DOCTOR rushes down the hallway.",
            "",
            "EXT. CITY STREET - NIGHT",
            "The street is nearly empty.",
        ]
        detector = SceneDetector()
        result = detector.detect(self._make_result(lines))

        self.assertEqual(len(result), 3)  # preamble + 2
        self.assertEqual(result[1].int_ext, "INT")
        self.assertEqual(result[2].int_ext, "EXT")

    def test_fdx_metadata(self):
        lines = [
            "INT. OFFICE - DAY",
            "John sits at his desk.",
            "EXT. PARK - NIGHT",
            "Mary walks her dog.",
        ]
        line_metadata = {
            0: {"type": "Scene Heading"},
            2: {"type": "Scene Heading"},
        }
        result = ParseResult(lines=lines, line_metadata=line_metadata)
        detector = SceneDetector()
        scene_list = detector.detect(result)

        self.assertEqual(len(scene_list), 2)
        self.assertEqual(scene_list[0].confidence, 1.0)

    def test_no_scenes(self):
        lines = ["Just some text.", "No scene headings here."]
        detector = SceneDetector()
        result = detector.detect(self._make_result(lines))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].confidence, 0.0)

    def test_empty(self):
        detector = SceneDetector()
        result = detector.detect(self._make_result([]))
        self.assertEqual(len(result), 0)


class TestSceneListManipulation(unittest.TestCase):

    def _build_scene_list(self):
        lines = [
            "第1场 内 医院走廊 - 日",
            "医生走过走廊。",
            "第2场 外 街道 - 夜",
            "行人稀少。",
            "第3场 内 办公室 - 日",
            "电话响了。",
        ]
        detector = SceneDetector()
        return detector.detect(ParseResult(lines=lines)), lines

    def test_insert_break(self):
        sl, lines = self._build_scene_list()
        count_before = len(sl)
        sl.insert_break(1, lines)
        self.assertEqual(len(sl), count_before + 1)

    def test_merge_scenes(self):
        sl, _ = self._build_scene_list()
        count_before = len(sl)
        sl.merge_scenes(0, 1)
        self.assertEqual(len(sl), count_before - 1)

    def test_remove_scene(self):
        sl, _ = self._build_scene_list()
        count_before = len(sl)
        sl.remove_scene(1)
        self.assertEqual(len(sl), count_before - 1)


if __name__ == "__main__":
    unittest.main()
