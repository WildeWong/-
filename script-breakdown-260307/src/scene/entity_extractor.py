"""Rule-based entity extraction for screenplay scenes."""
import re
from .models import Scene


# ── Exclusion lists ──────────────────────────────────────────────

# Terms that look like names but are actually directions / headings
_EXCLUDE_NAMES: set[str] = {
    # English scene / transition directions
    "INT", "EXT", "INTERIOR", "EXTERIOR",
    "CUT TO", "CUT", "FADE IN", "FADE OUT", "FADE TO", "FADE",
    "DISSOLVE TO", "DISSOLVE", "SMASH CUT", "MATCH CUT", "JUMP CUT",
    "CONTINUED", "CONT", "CONT'D", "CONTINUING", "THE END", "END",
    "SCENE", "SCENES", "ACT", "SEQUENCE", "UNIT",
    "TITLE", "CARD", "SUPER", "SUBTITLE", "TITLES",
    "CLOSE ON", "CLOSE UP", "CLOSEUP", "ANGLE ON", "WIDE ON", "WIDE SHOT",
    "POINT OF VIEW", "POV", "INTERCUT", "INTERCUT WITH",
    "BACK TO", "RETURN TO", "WE SEE", "WE HEAR",
    "V.O", "V.O.", "O.S.", "O.C.", "O.S", "O.C", "VO", "OS",
    "FLASHBACK", "FLASH FORWARD", "MONTAGE", "END MONTAGE", "BEGIN MONTAGE",
    "DAY", "NIGHT", "DAWN", "DUSK", "MORNING", "EVENING", "AFTERNOON",
    "LATER", "CONTINUOUS", "MOMENTS LATER", "SIMULTANEOUSLY", "SAME TIME",
    "ESTABLISHING", "AERIAL", "OVERHEAD", "TRACKING", "CLOSE",
    "BEGIN", "END", "START", "STOP",
    "NOTE", "NOTES", "PAGE",
    # Chinese scene / direction markers
    "内", "外", "日", "夜", "晨", "黄昏", "傍晚", "深夜", "清晨", "午后",
    "场", "幕", "第", "内景", "外景", "景", "镜头",
    "旁白", "画外音", "字幕", "解说", "旁白者",
    "闪回", "闪前", "蒙太奇", "结束", "开场", "序幕", "尾声",
    "同时", "继续", "稍后", "随后", "之后", "与此同时",
    "叠印", "淡入", "淡出", "切入", "切出",
}

# Single-char or purely punctuation names that slip through
_MIN_NAME_LEN = 2


def _is_valid_name(name: str) -> bool:
    """Return True if the extracted token looks like a real character name."""
    name = name.strip()
    if len(name) < _MIN_NAME_LEN:
        return False
    if name in _EXCLUDE_NAMES or name.upper() in _EXCLUDE_NAMES:
        return False
    # Pure numbers are not names
    if name.isdigit():
        return False
    # Must have at least one letter/CJK char
    cleaned = re.sub(r"[\s\.\'\-·•,，。、]", "", name)
    if not cleaned:
        return False
    # Very long strings are directions, not names
    if len(name) > 22:
        return False
    return True


# ── Character extraction patterns ────────────────────────────────

# Chinese dialogue cue:
#   张三：     张三:     (pure name)
#   张三（激动）：   张三(激动):   (name + parenthetical before colon)
#   A·B（激动）：   mixed with middle-dot
#   Allows up to 14 chars to cover compound names like "男主·大卫"
_CN_DIALOGUE_RE = re.compile(
    r'^[ \t]*'
    r'([一-龥a-zA-Z\d·•]{1,14})'        # name (Chinese + ASCII letters/digits + dots)
    r'(?:[ \t]*[（(][^）)\n]{0,30}[）)])?'  # optional parenthetical (e.g. 激动)
    r'[ \t]*[：:](?!\d)',                 # colon (not followed by digit, avoids time "12:30")
    re.MULTILINE,
)

# Chinese action line:  张三（拿起杯子）— name followed immediately by paren
_CN_ACTION_RE = re.compile(
    r'^[ \t]*([一-龥a-zA-Z\d·•]{2,12})[（(]',
    re.MULTILINE,
)

# English ALL-CAPS character cue (standard screenplay format):
#   "        JOHN" or "        JOHN (V.O.)"
#   Relaxed from 10+ to 4+ leading spaces to handle varied indentation.
_EN_CHARACTER_RE = re.compile(
    r'^\s{4,}([A-Z][A-Z\s\'\-\.]{1,30}?)\s*(?:\([^)]*\))?\s*$',
    re.MULTILINE,
)

# English "Name:" attribution (e.g. "JOHN: Hello there" or "John: Hello"):
#   Name starts with uppercase, colon, then non-whitespace content on same line.
_EN_COLON_DIALOGUE_RE = re.compile(
    r'^([A-Z][A-Za-z\s\'\-\.]{1,25}):\s+\S',
    re.MULTILINE,
)


def extract_characters_by_rules(scene: Scene) -> list[str]:
    """Extract character names from a scene using regex patterns."""
    text = scene.content
    names: set[str] = set()

    # ── Chinese patterns ──
    for m in _CN_DIALOGUE_RE.finditer(text):
        name = m.group(1).strip()
        if _is_valid_name(name):
            names.add(name)

    for m in _CN_ACTION_RE.finditer(text):
        name = m.group(1).strip()
        if _is_valid_name(name):
            names.add(name)

    # ── English patterns ──
    for m in _EN_CHARACTER_RE.finditer(text):
        name = m.group(1).strip()
        if _is_valid_name(name):
            names.add(name)

    for m in _EN_COLON_DIALOGUE_RE.finditer(text):
        name = m.group(1).strip()
        # Extra filter: ALL CAPS attribution lines are more reliable;
        # mixed-case "Name:" may be a location or direction label.
        if _is_valid_name(name) and not any(
            name.upper().startswith(excl) for excl in (
                "INT", "EXT", "CUT", "FADE", "DISSOLVE", "SCENE", "ACT",
                "NOTE", "PAGE",
            )
        ):
            names.add(name)

    return sorted(names)


# ── Props extraction ──────────────────────────────────────────────

# Chinese props in parenthetical action descriptions
_CN_PROPS_RE = re.compile(
    r'[（(]([^）)\n]{2,30})[）)]',
)

# Common prop keywords (Chinese)
_CN_PROP_KEYWORDS = [
    "刀", "枪", "剑", "棍", "杯", "碗", "筷", "盘", "瓶", "钥匙",
    "手机", "电话", "电脑", "笔记本", "书", "信", "照片", "地图",
    "包", "箱", "袋", "车", "自行车", "摩托", "药", "烟", "酒",
    "伞", "帽", "眼镜", "戒指", "项链", "手表", "钱", "钱包",
    "文件", "合同", "证件", "身份证", "护照", "票",
]

# English props in action verbs
_EN_PROPS_RE = re.compile(
    r'\b(?:picks?\s+up|grabs?|holds?|pulls?\s+out|takes?|puts?\s+down|drops?|carries|hands)\b'
    r'\s+(?:a\s+|the\s+|an\s+)?([a-zA-Z\s]{2,25})',
    re.IGNORECASE,
)

_EN_PROP_KEYWORDS = [
    "gun", "knife", "phone", "letter", "book", "key", "car", "bag",
    "bottle", "glass", "cup", "briefcase", "suitcase", "file", "folder",
    "ring", "watch", "cigarette", "wallet", "photograph", "photo",
    "map", "newspaper", "pen", "envelope", "badge", "flashlight",
    "rope", "tape", "camera", "laptop", "tablet", "umbrella",
]


def extract_props_by_rules(scene: Scene) -> list[str]:
    """Extract props/items from a scene using regex patterns and keywords."""
    text = scene.content
    props: set[str] = set()

    # Chinese: look for prop keywords in the text
    for kw in _CN_PROP_KEYWORDS:
        if kw in text:
            props.add(kw)

    # Chinese: extract from parenthetical actions
    for m in _CN_PROPS_RE.finditer(text):
        action = m.group(1)
        for kw in _CN_PROP_KEYWORDS:
            if kw in action:
                props.add(kw)

    # English: extract props from action verbs
    for m in _EN_PROPS_RE.finditer(text):
        prop = m.group(1).strip().lower()
        if prop and len(prop) > 1:
            props.add(prop)

    # English: look for prop keywords
    text_lower = text.lower()
    for kw in _EN_PROP_KEYWORDS:
        if kw in text_lower:
            props.add(kw)

    return sorted(props)


# ── Combined extraction ───────────────────────────────────────────

def extract_entities(scene: Scene) -> dict:
    """Extract all entities from a scene using rules.

    Returns:
        {"characters": [...], "props": [...], "scene_type": "", "scene_type_key": ""}
    """
    return {
        "characters": extract_characters_by_rules(scene),
        "props": extract_props_by_rules(scene),
        "scene_type": "",
        "scene_type_key": "",   # 将由 duration engine classify_scene 填充
    }
