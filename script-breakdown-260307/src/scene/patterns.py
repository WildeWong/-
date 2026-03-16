"""Scene heading pattern library for Chinese and English screenplays."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PatternMatch:
    """A matched scene heading pattern."""
    line_index: int
    heading: str
    int_ext: str
    location: str
    time_of_day: str
    confidence: float
    pattern_name: str


# Chinese number mapping
_CN_DIGITS = "零一二三四五六七八九十百千"
_CN_NUM_PATTERN = f"[{_CN_DIGITS}\\d]+"

# ── Chinese Patterns ──────────────────────────────────────────────

# Pattern: 第X场 / 第X幕，可选(上/下/续/补)分场标记
# e.g. "第1场 内 医院走廊 - 日" or "第2场(上)" or "第3幕(下) 外 街道 - 夜"
CH_SCENE_NUMBERED = re.compile(
    rf"^[\s　]*第\s*({_CN_NUM_PATTERN})\s*[场幕](?:\s*[（(](?:上|下|续|补)[）)])?[\s　:：]*(.*)$"
)

# Pattern: 场景X：description
CH_SCENE_LABEL = re.compile(
    rf"^[\s　]*场景\s*(\d+)\s*[：:][\s　]*(.*)$"
)

# Pattern: 数字. 内/外/内外 场景地点 - 日/夜
# e.g. "1. 内 医院走廊 - 日" or "23. 外 街道 - 夜"
CH_NUMBERED_INT_EXT = re.compile(
    r"^[\s　]*(\d+)\s*[\.、．]\s*(内景?|外景?|内外)\s+(.+?)\s*[-—–]\s*(.+?)[\s　]*$"
)

# Pattern: 数字. 场景地点/子地点/时间
# e.g. "1. 医院/走廊/日"
CH_NUMBERED_SLASH = re.compile(
    r"^[\s　]*(\d+)\s*[\.、．]\s*(.+?)[/／](.+?)[/／](.+?)[\s　]*$"
)

# Pattern: 【第X场】 or [第X场]
CH_BRACKETED = re.compile(
    rf"^[\s　]*[【\[]第\s*({_CN_NUM_PATTERN})\s*[场幕][】\]][\s　]*(.*)$"
)

# Pattern: 集-场号 with period + description (compact or spaced)
# e.g. "1-1.罗氏娱乐城赌场走廊内夜" or "1-21.拳手营帐营寨内/外夜" or "1-2A.医院内日"
CH_EPISODE_SCENE = re.compile(
    r"^[\s　]*(\d+)\s*[-]\s*(\d+[A-Za-z]?)\s*[\.、．]\s*(.*)$"
)

# Pattern: 集-场号 without period, followed by int/ext or Chinese location
# e.g. "1-1 内 医院走廊 - 日" or "2-3 外 街道 夜" or "1-1A 内走廊日"
CH_EPISODE_SCENE_NODOT = re.compile(
    r"^[\s　]*(\d+)\s*[-]\s*(\d+[A-Za-z]?)\s+((?:内景?|外景?|内外)[\s　\S]{0,}|[\u4e00-\u9fff][\s\S]{1,30})$"
)

# Pattern: 集-场号 standalone (just the number pair, nothing else)
# e.g. "1-1" or "2-3A"
CH_EPISODE_SCENE_BARE = re.compile(
    r"^[\s　]*(\d+)\s*[-]\s*(\d+[A-Za-z]?)[\s　]*$"
)

# Pattern: 数字+字母后缀 scene (alpha scene number)
# e.g. "1A. 内 医院走廊 - 日" or "2B.外 海滩 - 夜"
CH_ALPHA_SCENE = re.compile(
    r"^[\s　]*(\d+[A-Za-z])\s*[\.、．]\s*(.+)$"
)

# Pattern: 数字(上/下/续/补) subscene
# e.g. "1(上) 内 医院走廊 - 日" or "3(下)赌场外走廊夜" or "2(续)"
CH_SUBSCENE = re.compile(
    r"^[\s　]*(\d+)\s*[（(](上|下|续|补)[）)]\s*[\.、．]?\s*(.*)$"
)

# Pattern: Standalone int/ext line (no number prefix)
# e.g. "内 医院走廊 - 日" or "外 街道 - 夜"
CH_INT_EXT_ONLY = re.compile(
    r"^[\s　]*(内景?|外景?|内外|室内|室外)[\.．\s　]+(.+?)\s*[-—–]\s*(.+?)[\s　]*$"
)

# Pattern: 数字. 紧凑描述 (number + compact Chinese description with ie/tod)
# e.g. "1.医院走廊内景日" or "23. 赌场外夜" or "5. 客厅室内上午"
# Only accepted when _parse_compact_desc yields int_ext OR time_of_day
CH_NUMBERED_COMPACT = re.compile(
    r"^[\s　]*(\d+)\s*[\.、．]\s*([^\s\d].{1,70})$"
)

# Pattern: 第X幕第Y场 (act-scene hierarchical numbering)
# e.g. "第一幕第三场 内 医院 - 日"
_CN_NUM_PATTERN2 = "[零一二三四五六七八九十百千\\d]+"
CH_ACT_SCENE = re.compile(
    rf"^[\s　]*第\s*({_CN_NUM_PATTERN2})\s*幕第?\s*({_CN_NUM_PATTERN2})\s*[场][\s　]*(.*)$"
)

# Pattern: 场X / 场次X  (abbreviated scene marker)
# e.g. "场5 内 医院 - 日" or "场次3：医院走廊夜"
CH_SCENE_SHORT = re.compile(
    r"^[\s　]*场次?\s*(\d+)\s*[：:\.\s　]+(.*)$"
)


# ── English Patterns (Hollywood Standard) ────────────────────────

# Pattern: INT. / EXT. / INT./EXT. / I/E. with location and time
# e.g. "INT. HOSPITAL CORRIDOR - DAY"
EN_SCENE_HEADING = re.compile(
    r"^[\s]*(\d+\s*[\.)]?\s*)?"  # optional scene number
    r"(INT\.|EXT\.|INT\./EXT\.|INT/EXT\.|I/E\.)"
    r"\s+(.+?)"
    r"(?:\s*[-—–]\s*(.+?))?"
    r"[\s]*$",
    re.IGNORECASE,
)

# Pattern: Scene number prefix on its own line (less common)
EN_SCENE_NUMBER_LINE = re.compile(
    r"^[\s]*(\d+)\s*[\.)][\s]*$"
)


def match_chinese_patterns(line: str, line_index: int) -> PatternMatch | None:
    """Try to match a line against Chinese scene heading patterns."""

    # 第X幕第Y场 act-scene hierarchy — must be tried BEFORE CH_SCENE_NUMBERED
    # (CH_SCENE_NUMBERED also matches "第X幕" so it would steal these lines)
    m = CH_ACT_SCENE.match(line)
    if m:
        desc = m.group(3).strip()
        ie, loc, tod = _parse_chinese_desc(desc)
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=ie, location=loc, time_of_day=tod,
            confidence=0.92, pattern_name="CH_ACT_SCENE",
        )

    # 第X场 / 第X幕 (with optional subscene marker)
    m = CH_SCENE_NUMBERED.match(line)
    if m:
        desc = m.group(2).strip()
        ie, loc, tod = _parse_chinese_desc(desc)
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=ie, location=loc, time_of_day=tod,
            confidence=0.95, pattern_name="CH_SCENE_NUMBERED",
        )

    # 场景X：
    m = CH_SCENE_LABEL.match(line)
    if m:
        desc = m.group(2).strip()
        ie, loc, tod = _parse_chinese_desc(desc)
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=ie, location=loc, time_of_day=tod,
            confidence=0.90, pattern_name="CH_SCENE_LABEL",
        )

    # 数字. 内/外 地点 - 时间
    m = CH_NUMBERED_INT_EXT.match(line)
    if m:
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=_normalize_int_ext(m.group(2)),
            location=m.group(3).strip(),
            time_of_day=m.group(4).strip(),
            confidence=0.95, pattern_name="CH_NUMBERED_INT_EXT",
        )

    # 数字. 地点/子地点/时间
    m = CH_NUMBERED_SLASH.match(line)
    if m:
        location = m.group(2).strip() + "/" + m.group(3).strip()
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext="", location=location,
            time_of_day=m.group(4).strip(),
            confidence=0.85, pattern_name="CH_NUMBERED_SLASH",
        )

    # 【第X场】
    m = CH_BRACKETED.match(line)
    if m:
        desc = m.group(2).strip()
        ie, loc, tod = _parse_chinese_desc(desc)
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=ie, location=loc, time_of_day=tod,
            confidence=0.90, pattern_name="CH_BRACKETED",
        )

    # 集-场号.description (period required)
    m = CH_EPISODE_SCENE.match(line)
    if m:
        desc = m.group(3).strip()
        ie, loc, tod = _parse_compact_desc(desc)
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=ie, location=loc, time_of_day=tod,
            confidence=0.95, pattern_name="CH_EPISODE_SCENE",
        )

    # 数字+字母后缀: "1A. description"
    m = CH_ALPHA_SCENE.match(line)
    if m:
        desc = m.group(2).strip()
        ie, loc, tod = _parse_compact_desc(desc)
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=ie, location=loc, time_of_day=tod,
            confidence=0.90, pattern_name="CH_ALPHA_SCENE",
        )

    # 数字(上/下): "1(上) 内 医院 - 日" or "3(下)走廊外夜"
    m = CH_SUBSCENE.match(line)
    if m:
        desc = m.group(3).strip()
        ie, loc, tod = _parse_compact_desc(desc)
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=ie, location=loc, time_of_day=tod,
            confidence=0.90, pattern_name="CH_SUBSCENE",
        )

    # 集-场号 without period + description starting with int/ext or Chinese
    m = CH_EPISODE_SCENE_NODOT.match(line)
    if m:
        desc = m.group(3).strip()
        ie, loc, tod = _parse_compact_desc(desc)
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=ie, location=loc, time_of_day=tod,
            confidence=0.80, pattern_name="CH_EPISODE_SCENE_NODOT",
        )

    # 集-场号 bare (standalone, just "1-1" or "2-3A")
    m = CH_EPISODE_SCENE_BARE.match(line)
    if m:
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext="", location="", time_of_day="",
            confidence=0.75, pattern_name="CH_EPISODE_SCENE_BARE",
        )

    # 内/外 地点 - 时间 (no number)
    m = CH_INT_EXT_ONLY.match(line)
    if m:
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=_normalize_int_ext(m.group(1)),
            location=m.group(2).strip(),
            time_of_day=m.group(3).strip(),
            confidence=0.80, pattern_name="CH_INT_EXT_ONLY",
        )

    # 场X / 场次X short form
    m = CH_SCENE_SHORT.match(line)
    if m:
        desc = m.group(2).strip()
        ie, loc, tod = _parse_compact_desc(desc)
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=ie, location=loc, time_of_day=tod,
            confidence=0.88, pattern_name="CH_SCENE_SHORT",
        )

    # 数字. 紧凑描述 — only when compact parse yields int_ext OR time_of_day
    m = CH_NUMBERED_COMPACT.match(line)
    if m:
        desc = m.group(2).strip()
        ie, loc, tod = _parse_compact_desc(desc)
        if ie or tod:   # require evidence of scene structure
            return PatternMatch(
                line_index=line_index, heading=line.strip(),
                int_ext=ie, location=loc, time_of_day=tod,
                confidence=0.85, pattern_name="CH_NUMBERED_COMPACT",
            )

    return None


def match_english_patterns(line: str, line_index: int) -> PatternMatch | None:
    """Try to match a line against English (Hollywood) scene heading patterns."""
    m = EN_SCENE_HEADING.match(line)
    if m:
        int_ext = m.group(2).upper().rstrip(".")
        location = m.group(3).strip() if m.group(3) else ""
        tod = m.group(4).strip() if m.group(4) else ""
        return PatternMatch(
            line_index=line_index, heading=line.strip(),
            int_ext=int_ext, location=location, time_of_day=tod,
            confidence=0.95, pattern_name="EN_SCENE_HEADING",
        )
    return None


def match_all_patterns(line: str, line_index: int) -> PatternMatch | None:
    """Try all patterns (Chinese first, then English) and return best match."""
    result = match_chinese_patterns(line, line_index)
    if result:
        return result
    return match_english_patterns(line, line_index)


def _parse_chinese_desc(desc: str) -> tuple[str, str, str]:
    """Parse a Chinese scene description into (int_ext, location, time_of_day)."""
    if not desc:
        return "", "", ""
    # Try: 内/外 地点 - 时间  (separator: space, dot, or middle-dot ·)
    m = re.match(r"(内景?|外景?|内外)[\.．·\s　]+(.+?)\s*[-—–·]\s*(.+)", desc)
    if m:
        return _normalize_int_ext(m.group(1)), m.group(2).strip(), m.group(3).strip()
    # Try: 内/外，地点，时间  (comma-separated — common in Chinese TV scripts)
    m = re.match(r"(内景?|外景?|内外)[，,]\s*(.+?)[，,]\s*(.+)", desc)
    if m:
        return _normalize_int_ext(m.group(1)), m.group(2).strip(), m.group(3).strip()
    # Try: 地点 - 时间  (no int_ext prefix, dash or ·)
    m = re.match(r"(.+?)\s*[-—–·]\s*(.+)", desc)
    if m:
        return "", m.group(1).strip(), m.group(2).strip()
    return "", desc, ""


def _parse_compact_desc(desc: str) -> tuple[str, str, str]:
    """Parse a compact Chinese scene description like '罗氏娱乐城赌场走廊内夜'.

    Handles multiple formats:
    - Separator style:  内 地点 - 时间  /  地点 - 时间
    - Space style:      内 地点 时间    /  地点 时间
    - Slash style:      地点/内景/时间  /  地点/内/夜
    - Compact style:    地点内夜        /  地点内景夜
    """
    if not desc:
        return "", "", ""

    # Time of day variants (extended to cover common Chinese script conventions)
    _TOD = (
        r"(日|夜|晨|黄昏|日间|夜间|傍晚|清晨|上午|下午|午夜|子夜|深夜|黎明|凌晨|"
        r"DAY|NIGHT|DAWN|DUSK|MORNING|AFTERNOON|EVENING|MIDNIGHT)"
    )
    # Int/Ext variants including 室内/室外 synonyms
    _IE = r"(内景?|外景?|内外景?|内/外|室内|室外)"

    # 1. Separator style: 内/外 地点 - 时间  or  地点 - 时间
    ie, loc, tod = _parse_chinese_desc(desc)
    if tod:
        return ie, loc, tod

    # 2. Space style: 内/外 地点 时间 (no dash, int_ext prefix)
    m = re.match(rf"{_IE}[\.．\s　]+(.+?)\s+{_TOD}[\s　]*$", desc)
    if m:
        return _normalize_int_ext(m.group(1)), m.group(2).strip(), m.group(3).strip()

    # 2.5. Space-separated with multi-word location: 地点(可多词) int_ext 时间
    # e.g. "唐楼 街头 外 日" / "医院 走廊 内 夜"
    # The non-greedy (.+?) stops at the first valid int_ext + time suffix.
    m = re.match(rf"^(.+?)\s+{_IE}\s+{_TOD}[\s　]*$", desc)
    if m:
        return _normalize_int_ext(m.group(2)), m.group(1).strip(), m.group(3).strip()

    # 3. Slash style: 地点/内景/时间  or  内景/地点/时间
    m = re.match(rf"^(.+?)[/／]{_IE}[/／]{_TOD}[\s　]*$", desc)
    if m:
        return _normalize_int_ext(m.group(2)), m.group(1).strip(), m.group(3).strip()
    # slash reversed: 内/地点/时间
    m = re.match(rf"^{_IE}[/／](.+?)[/／]{_TOD}[\s　]*$", desc)
    if m:
        return _normalize_int_ext(m.group(1)), m.group(2).strip(), m.group(3).strip()
    # slash: 地点/时间 (no int_ext)
    m = re.match(rf"^(.+?)[/／]{_TOD}[\s　]*$", desc)
    if m:
        return "", m.group(1).strip(), m.group(2).strip()

    # 4. Compact style (no separators): 地点内夜 / 地点室内夜 / 地点内景夜
    # Put longer alternatives first so "室内"/"室外" are tried before bare "内"/"外"
    m = re.match(rf"^(.+?)(室内|室外|内/外景?|内外景?|内景|外景|内|外){_TOD}[\s　]*$", desc)
    if m:
        return _normalize_int_ext(m.group(2)), m.group(1).strip(), m.group(3).strip()

    # 4.5. Standalone int_ext + time, NO location: "外日" / "内夜" / "外景日"
    # Must be tried before step 5 so "外日" isn't mistaken for a location-only line.
    m = re.match(rf"^{_IE}{_TOD}[\s　]*$", desc)
    if m:
        return _normalize_int_ext(m.group(1)), "", m.group(2).strip()

    # 5. Compact without time: 地点内 / 地点室内 / 地点外景
    m = re.match(rf"^(.+?)(室内|室外|内/外景?|内外景?|内景|外景|内|外)[\s　]*$", desc)
    if m:
        return _normalize_int_ext(m.group(2)), m.group(1).strip(), ""

    # 6. Space style no int_ext: 地点 时间
    m = re.match(rf"^(.+?)\s+{_TOD}[\s　]*$", desc)
    if m:
        return "", m.group(1).strip(), m.group(2).strip()

    # 7. Fallback: treat whole desc as location
    return "", desc, ""


def _normalize_int_ext(value: str) -> str:
    """Normalize int/ext values."""
    value = value.strip()
    if value in ("内", "内景", "室内"):
        return "内"
    if value in ("外", "外景", "室外"):
        return "外"
    if value in ("内外", "内外景", "内/外", "内/外景"):
        return "内外"
    return value


def parse_heading_fields(heading: str) -> dict:
    """Extract int_ext, location, time_of_day from an arbitrary heading string.

    Returns a dict with keys: int_ext, location, time_of_day.
    Empty strings when fields cannot be determined.
    """
    if not heading:
        return {"int_ext": "", "location": "", "time_of_day": ""}

    # Try full pattern match first
    m = match_all_patterns(heading, 0)
    if m and (m.int_ext or m.location or m.time_of_day):
        return {
            "int_ext": m.int_ext,
            "location": m.location,
            "time_of_day": m.time_of_day,
        }

    # Try to parse the heading directly as a compact description
    ie, loc, tod = _parse_compact_desc(heading)
    return {"int_ext": ie, "location": loc, "time_of_day": tod}
