"""
拍摄时长估算引擎
公式：(剧本页数 × 场景类型基准时间(表A) × 类型系数(表B)) + 额外时间因子(表C) + 转场时间
其中：剧本页数 = 行数 ÷ 每页行数（中文剧本默认30行），最低按 1/8 页计
"""
from __future__ import annotations

import json
import os


# ── 默认参数表 ──────────────────────────────────────────

DEFAULT_TABLE_A: dict = {
    "A1_简单对话":  {"label": "简单对话（室内，2-3人）",        "minutes": 12},
    "A2_群戏":      {"label": "群戏（4人以上）",                "minutes": 24},
    "A3_过场":      {"label": "过场/走戏/MOS",                  "minutes": 8},
    "A4_情绪重场":  {"label": "情绪重场戏（哭戏/爆发/对峙）",  "minutes": 24},
    "A5_亲密戏":    {"label": "亲密戏/床戏",                    "minutes": 30},
    "A6_轻动作":    {"label": "轻动作（推搡/追跑）",            "minutes": 25},
    "A7_武戏":      {"label": "中重度武戏/战争",                "minutes": 50},
    "A8_大场面":    {"label": "大场面（典礼/朝堂/婚礼）",      "minutes": 50},
    "A9_特殊环境":  {"label": "特殊环境（雨/雪/夜外/车戏）",   "minutes": 30},
    "A10_特殊对象": {"label": "特殊对象（儿童/动物）",          "minutes": 36},
}

DEFAULT_TABLE_B: dict = {
    "B1_现代都市":   {"label": "现代都市剧（基准）",         "factor": 1.00},
    "B2_甜宠":       {"label": "甜宠剧",                     "factor": 0.85},
    "B3_悬疑犯罪":   {"label": "悬疑/犯罪剧",                "factor": 1.25},
    "B4_年代剧":     {"label": "年代剧（民国/90年代等）",     "factor": 1.25},
    "B5_古装":       {"label": "古装剧",                     "factor": 1.40},
    "B6_玄幻仙侠":   {"label": "玄幻/仙侠剧",                "factor": 1.75},
    "B7_主旋律军旅": {"label": "主旋律/军旅剧",               "factor": 1.40},
    "B8_竖屏微短剧": {"label": "竖屏微短剧",                 "factor": 0.55},
}

DEFAULT_TABLE_C: dict = {
    "C1_妆发现代":     {"label": "妆发——现代",                    "minutes": 45,  "note": "每日首场/换造型"},
    "C2_妆发古装":     {"label": "妆发——古装",                    "minutes": 135, "note": "每日首场/换造型"},
    "C3_妆发特效":     {"label": "妆发——特效妆",                  "minutes": 240, "note": "每日首场/换造型"},
    "C4_古装群演妆发": {"label": "古装群演妆发（50人级）",         "minutes": 180, "note": "有古装群演日"},
    "C5_转场移动":     {"label": "转场/移动",                     "minutes": 105, "note": "每次换拍摄地"},
    "C6_场景翻转":     {"label": "场景翻转（换布光方向）",         "minutes": 45,  "note": "反打/换方向时"},
    "C7_排练简单":     {"label": "排练——简单",                    "minutes": 15,  "note": "普通走位"},
    "C8_排练复杂":     {"label": "排练——复杂/群戏/武戏",          "minutes": 50,  "note": "调度复杂场景"},
    "C9_灯光简单":     {"label": "灯光布置——简单",                "minutes": 20,  "note": "常规室内"},
    "C10_灯光复杂":    {"label": "灯光布置——复杂",                "minutes": 60,  "note": "夜戏/氛围/大场面"},
    "C11_餐休":        {"label": "餐休",                          "minutes": 40,  "note": "每日2次"},
    "C12_清场":        {"label": "清场（亲密/敏感戏）",            "minutes": 20,  "note": "床戏/敏感内容"},
    "C13_特殊准备":    {"label": "特殊准备（造雨/造雪/爆破审批）","minutes": 50,  "note": "对应特殊环境"},
    "C14_每日缓冲":    {"label": "每日缓冲（天气/审查/杂项）",    "minutes": 30,  "note": "建议每日固定预留"},
}

# ── 默认关键词规则表（按 priority 降序匹配）──────────────────

DEFAULT_KEYWORD_RULES: dict = {
    "A7_武戏": {
        "keywords": ["打", "斗", "武", "搏", "刺", "砍", "劈", "踢", "拳", "剑",
                     "枪战", "格斗", "厮杀", "交锋", "决斗", "追杀", "肉搏",
                     "飞踢", "过招", "拔剑", "挥刀", "战斗", "战争", "冲锋"],
        "priority": 100,
        "description": "检测到动作/武打相关关键词",
    },
    "A5_亲密戏": {
        "keywords": ["吻", "床", "亲密", "缠绵", "拥抱", "抚摸", "依偎",
                     "脱", "裸", "激情", "肌肤", "相拥"],
        "priority": 95,
        "description": "检测到亲密戏相关关键词",
    },
    "A8_大场面": {
        "keywords": ["典礼", "朝堂", "婚礼", "宴会", "大殿", "阅兵", "登基",
                     "祭祀", "出征", "凯旋", "庆典", "盛宴", "集会", "仪式",
                     "群臣", "百官", "万人"],
        "priority": 90,
        "description": "检测到大场面相关关键词",
    },
    "A9_特殊环境": {
        "keywords": ["雨", "雪", "暴风", "车内", "车戏", "水下", "泳池",
                     "爆炸", "火灾", "坍塌", "悬崖", "高空", "地下",
                     "造雨", "造雪", "烟雾"],
        "priority": 85,
        "description": "检测到特殊环境相关关键词",
    },
    "A10_特殊对象": {
        "keywords": ["儿童", "小孩", "婴儿", "幼儿", "孩子哭", "动物", "狗",
                     "猫", "马", "骑马", "鸟", "宠物", "牲畜"],
        "priority": 80,
        "description": "检测到儿童/动物相关关键词",
    },
    "A4_情绪重场": {
        "keywords": ["哭", "泪", "崩溃", "爆发", "怒吼", "嘶吼", "嚎啕",
                     "对峙", "摊牌", "撕破脸", "决裂", "绝望", "癫狂",
                     "痛哭", "失声", "颤抖", "咆哮", "质问"],
        "priority": 75,
        "description": "检测到强情绪相关关键词",
    },
    "A6_轻动作": {
        "keywords": ["推", "搡", "追", "跑", "摔", "倒", "拽", "拉扯",
                     "挣扎", "逃", "闪躲", "滑倒", "碰撞", "扭打"],
        "priority": 70,
        "description": "检测到轻动作相关关键词",
    },
    "A3_过场": {
        "keywords": ["过场", "走戏", "空镜", "转场", "闪回", "回忆",
                     "旁白", "独白画外", "MOS", "黑屏", "字幕"],
        "priority": 60,
        "description": "检测到过场/非表演性内容",
    },
    "A2_群戏": {
        "keywords": [],       # 群戏主要靠角色数量判断
        "priority": 50,
        "min_cast": 4,        # 4人以上自动归为群戏
        "description": "4人以上群戏",
    },
    "A1_简单对话": {
        "keywords": [],       # 默认兜底
        "priority": 0,
        "description": "常规对话场景（默认）",
    },
}


# ── DurationParams ──────────────────────────────────────

class DurationParams:
    """用户可自定义的时长估算参数集（支持持久化）"""

    def __init__(
        self,
        table_a: dict | None = None,
        table_b: dict | None = None,
        table_c: dict | None = None,
        genre_key: str = "B1_现代都市",
        transition_base: int = 40,
        lines_per_page: int = 30,           # 中文剧本默认 30 行/页
        min_pages: float = 0.125,           # 最低 1/8 页
        custom_scene_types: dict | None = None,  # 用户自定义场景类型
        keyword_rules: dict | None = None,       # 关键词规则（可覆盖默认）
    ) -> None:
        self.table_a = table_a or dict(DEFAULT_TABLE_A)
        self.table_b = table_b or dict(DEFAULT_TABLE_B)
        self.table_c = table_c or dict(DEFAULT_TABLE_C)
        self.genre_key = genre_key
        self.transition_base = transition_base
        self.lines_per_page = lines_per_page
        self.min_pages = min_pages
        self.custom_scene_types = custom_scene_types or {}
        self.keyword_rules = keyword_rules or dict(DEFAULT_KEYWORD_RULES)

    @property
    def genre_factor(self) -> float:
        entry = self.table_b.get(self.genre_key, {})
        return entry.get("factor", 1.0) if isinstance(entry, dict) else 1.0

    def to_dict(self) -> dict:
        return {
            "table_a": self.table_a,
            "table_b": self.table_b,
            "table_c": self.table_c,
            "genre_key": self.genre_key,
            "transition_base": self.transition_base,
            "lines_per_page": self.lines_per_page,
            "min_pages": self.min_pages,
            "custom_scene_types": self.custom_scene_types,
            "keyword_rules": self.keyword_rules,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DurationParams":
        if not d:
            return cls()
        return cls(
            table_a=d.get("table_a"),
            table_b=d.get("table_b"),
            table_c=d.get("table_c"),
            genre_key=d.get("genre_key", "B1_现代都市"),
            transition_base=d.get("transition_base", 40),
            lines_per_page=d.get("lines_per_page", 30),
            min_pages=d.get("min_pages", 0.125),
            custom_scene_types=d.get("custom_scene_types"),
            keyword_rules=d.get("keyword_rules"),
        )

    def save(self, path: str) -> None:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            import json
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "DurationParams":
        if not os.path.exists(path):
            return cls()
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except Exception:
            return cls()


# ── SceneDurationEngine ─────────────────────────────────

class SceneDurationEngine:
    """
    核心公式：
    拍摄时长(分) = 页数 × 场景类型基准时间(表A) × 类型系数(表B)
                  + 额外时间因子(表C，按条件叠加)
                  + 转场时间(转场基础 × 类型系数)

    页数 = max(行数 ÷ lines_per_page, min_pages)
    """

    def __init__(self, params: DurationParams | None = None) -> None:
        self.params = params or DurationParams()

    def classify_scene(
        self,
        scene: object,
        entities: dict,
        script_content: str = "",
    ) -> dict:
        """
        自动分类场景类型，返回：
        {
            "a_key": "A7_武戏",
            "confidence": "high" / "medium" / "low",
            "method": "manual" / "keyword" / "cast_count" / "default",
            "matched_keywords": ["打", "斗"],
            "detail": "检测到关键词：打、斗",
        }

        分类策略（按优先级）：
        1. 用户手动指定（entities 中已有 scene_type_key）
        2. 关键词匹配（标题 + 摘要 + scene_type + 正文）
        3. 演员数量推断
        4. 默认 → 简单对话
        """
        ent = entities or {}

        # ── 来源1：用户手动指定 ─────────────────────────────
        manual_key = str(ent.get("scene_type_key", "") or "").strip()
        if manual_key:
            if manual_key in self.params.table_a or manual_key in self.params.custom_scene_types:
                return {
                    "a_key": manual_key,
                    "confidence": "high",
                    "method": "manual",
                    "matched_keywords": [],
                    "detail": "用户手动指定",
                }

        # ── 构建搜索文本 ──────────────────────────────────────
        heading = str(getattr(scene, "heading", "") or "")
        summary = str(getattr(scene, "summary", "") or "")
        scene_type_text = str(ent.get("scene_type", "") or "")
        content = str(script_content or "")
        all_text = " ".join([heading, summary, scene_type_text, content])
        all_text_lower = all_text.lower()

        # ── 来源2：关键词匹配 ─────────────────────────────────
        rules: dict = dict(self.params.keyword_rules)
        # 合并用户自定义类型的关键词规则
        for k, v in self.params.custom_scene_types.items():
            if k not in rules and isinstance(v, dict) and v.get("keywords"):
                rules[k] = v

        # 按 priority 降序
        sorted_rules = sorted(
            rules.items(),
            key=lambda x: x[1].get("priority", 0) if isinstance(x[1], dict) else 0,
            reverse=True,
        )

        for a_key, rule in sorted_rules:
            if not isinstance(rule, dict):
                continue
            keywords = rule.get("keywords", [])
            if not keywords:
                continue
            matched = [kw for kw in keywords if kw in all_text_lower]
            if matched:
                return {
                    "a_key": a_key,
                    "confidence": "high" if len(matched) >= 2 else "medium",
                    "method": "keyword",
                    "matched_keywords": matched[:5],
                    "detail": f"检测到关键词：{'、'.join(matched[:5])}",
                }

        # ── 特殊规则：夜外景 ─────────────────────────────────
        int_ext = str(getattr(scene, "int_ext", "") or "").lower()
        time_of_day = str(getattr(scene, "time_of_day", "") or "").lower()
        if "夜" in time_of_day and "外" in int_ext:
            return {
                "a_key": "A9_特殊环境",
                "confidence": "medium",
                "method": "attribute",
                "matched_keywords": [],
                "detail": "夜间外景，自动归入特殊环境",
            }

        # ── 来源3：演员数量推断 ───────────────────────────────
        cast_count = len(ent.get("characters", []))
        for a_key, rule in sorted_rules:
            if not isinstance(rule, dict):
                continue
            min_cast = rule.get("min_cast", 0)
            if min_cast > 0 and cast_count >= min_cast:
                return {
                    "a_key": a_key,
                    "confidence": "medium",
                    "method": "cast_count",
                    "matched_keywords": [],
                    "detail": f"检测到{cast_count}个角色 ≥ {min_cast}人",
                }

        # ── 来源4：默认 ───────────────────────────────────────
        return {
            "a_key": "A1_简单对话",
            "confidence": "low",
            "method": "default",
            "matched_keywords": [],
            "detail": "未匹配到特征，默认为简单对话",
        }

    def get_applicable_c_factors(
        self,
        scene: object,
        entities: dict,
        a_key: str,
        is_first_of_day: bool = False,
        is_location_change: bool = False,
    ) -> list[str]:
        """
        根据场景类型和属性判断哪些表C因子需要叠加。
        接受 a_key 字符串（已由 classify_scene 确定）。
        """
        time_of_day = str(getattr(scene, "time_of_day", "") or "")
        factors: list[str] = []

        # 排练
        if a_key in ("A7_武戏", "A8_大场面", "A2_群戏"):
            factors.append("C8_排练复杂")
        elif a_key != "A3_过场":
            factors.append("C7_排练简单")

        # 灯光
        if a_key in ("A7_武戏", "A8_大场面", "A9_特殊环境") or "夜" in time_of_day:
            factors.append("C10_灯光复杂")
        else:
            factors.append("C9_灯光简单")

        # 清场
        if a_key == "A5_亲密戏":
            factors.append("C12_清场")

        # 特殊准备
        if a_key == "A9_特殊环境":
            factors.append("C13_特殊准备")

        # 转场
        if is_location_change:
            factors.append("C5_转场移动")

        return factors

    def estimate_scene(
        self,
        scene: object,
        entities: dict,
        script_content: str = "",
        is_first_of_day: bool = False,
        is_location_change: bool = False,
    ) -> dict:
        """
        估算单场拍摄时长，返回完整分解（含分类详情和公式）。
        """
        ent = entities or {}

        # 1. 页数（使用用户可配的 lines_per_page / min_pages）
        line_count = max(
            getattr(scene, "end_line", 0) - getattr(scene, "start_line", 0), 1
        )
        pages = max(line_count / self.params.lines_per_page, self.params.min_pages)

        # 2. 场景分类（返回 dict）
        classification = self.classify_scene(scene, ent, script_content)
        a_key = classification["a_key"]

        # 从表A或自定义类型中取基准时间
        if a_key in self.params.table_a:
            a_entry = self.params.table_a[a_key]
        elif a_key in self.params.custom_scene_types:
            a_entry = self.params.custom_scene_types[a_key]
        else:
            a_entry = {"label": a_key, "minutes": 12}

        a_minutes: int = a_entry["minutes"] if isinstance(a_entry, dict) else 12
        a_label: str = a_entry.get("label", a_key) if isinstance(a_entry, dict) else a_key

        # 3. 类型系数（表B）
        genre_factor = self.params.genre_factor

        # 4. 基础拍摄时间 = 页数 × 基准时间 × 类型系数
        base_minutes = pages * a_minutes
        after_genre = base_minutes * genre_factor

        # 5. 表C额外时间因子
        c_keys = self.get_applicable_c_factors(
            scene, ent, a_key, is_first_of_day, is_location_change
        )
        c_details: list[dict] = []
        c_total = 0
        for ck in c_keys:
            c_entry = self.params.table_c.get(ck, {"label": ck, "minutes": 0})
            c_min = c_entry["minutes"] if isinstance(c_entry, dict) else 0
            c_details.append({
                "key": ck,
                "label": c_entry.get("label", ck) if isinstance(c_entry, dict) else ck,
                "minutes": c_min,
            })
            c_total += c_min

        # 6. 转场时间
        transition = 0.0
        if is_location_change:
            transition = self.params.transition_base * genre_factor

        # 7. 合计
        total_minutes = after_genre + c_total + transition
        # 应用用户自定义额外因子（乘数叠加）
        custom_factors_list = ent.get("custom_factors", [])
        custom_multiplier = 1.0
        for cf in custom_factors_list:
            if isinstance(cf, dict) and "value" in cf:
                v = float(cf["value"])
                if v > 0:
                    custom_multiplier *= v
        if custom_multiplier != 1.0:
            total_minutes *= custom_multiplier
        total_hours = round(total_minutes / 60, 2)

        # 8. 公式字符串（供前端展示）
        c_desc = " + ".join(
            f"{d['label']}{d['minutes']}分" for d in c_details
        ) if c_details else "无"
        formula = (
            f"{pages:.2f}页 × {a_minutes}分({a_label}) × {genre_factor:.2f}(类型系数)"
            f" = {after_genre:.1f}分"
        )
        if c_total > 0:
            formula += f" + {c_total}分({c_desc})"
        if transition > 0:
            formula += f" + {transition:.0f}分(转场{self.params.transition_base}×{genre_factor:.2f})"
        formula += f" = 共{total_minutes:.1f}分 ≈ {total_hours}h"

        return {
            "scene_number": getattr(scene, "scene_number", 0),
            "classification": classification,
            "a_key": a_key,
            "a_label": a_label,
            "a_minutes": a_minutes,
            "genre_key": self.params.genre_key,
            "genre_factor": genre_factor,
            "pages": round(pages, 3),
            "lines_per_page": self.params.lines_per_page,
            "line_count": line_count,
            "base_minutes": round(base_minutes, 1),
            "after_genre": round(after_genre, 1),
            "c_factors": c_details,
            "c_total": c_total,
            "transition_minutes": round(transition, 1),
            "custom_factors": custom_factors_list,
            "custom_multiplier": round(custom_multiplier, 3),
            "total_minutes": round(total_minutes, 1),
            "total_hours": total_hours,
            "formula": formula,
        }

    def estimate_all(self, scenes: list, entities_map: dict) -> dict:
        """估算所有场次，返回 {scene_number: estimate_dict}。"""
        result: dict = {}
        for s in scenes:
            ent = entities_map.get(s.scene_number, {})
            result[s.scene_number] = self.estimate_scene(s, ent)
        return result

    def estimate_day_total(
        self,
        scene_ids: list,
        scenes_map: dict,
        entities_map: dict,
        genre_key: str | None = None,
    ) -> dict:
        """估算一个拍摄日的总时长，包含各场时间 + 每日固定开销。"""
        if genre_key:
            self.params.genre_key = genre_key

        scene_estimates: list[dict] = []
        prev_location: str | None = None

        for i, sid in enumerate(scene_ids):
            scene = scenes_map.get(sid)
            ent = entities_map.get(sid, {})
            if scene is None:
                continue
            loc = getattr(scene, "location", "") or ""
            is_loc_change = prev_location is not None and loc != prev_location
            est = self.estimate_scene(
                scene, ent,
                is_first_of_day=(i == 0),
                is_location_change=is_loc_change,
            )
            scene_estimates.append(est)
            prev_location = loc

        # 每日固定时间
        daily_fixed = 0
        if self.params.genre_key in ("B5_古装", "B6_玄幻仙侠"):
            daily_fixed += self.params.table_c.get("C2_妆发古装", {}).get("minutes", 135)
        else:
            daily_fixed += self.params.table_c.get("C1_妆发现代", {}).get("minutes", 45)
        daily_fixed += self.params.table_c.get("C11_餐休", {}).get("minutes", 40) * 2
        daily_fixed += self.params.table_c.get("C14_每日缓冲", {}).get("minutes", 30)

        scene_total = sum(e["total_minutes"] for e in scene_estimates)
        grand_total = scene_total + daily_fixed

        return {
            "scenes": scene_estimates,
            "scene_total_minutes": round(scene_total, 1),
            "daily_fixed_minutes": daily_fixed,
            "daily_fixed_breakdown": "妆发+餐休×2+缓冲",
            "total_minutes": round(grand_total, 1),
            "total_hours": round(grand_total / 60, 2),
        }

    def get_duration_map(self, scenes: list, entities_map: dict) -> dict:
        """返回简洁的 {scene_number: hours}，供 ScheduleConfig.scene_duration_map 使用。
        优先使用 entities 中的 duration_override_hours 手动覆盖值。"""
        result = {}
        for s in scenes:
            ent = entities_map.get(s.scene_number, {})
            override = ent.get("duration_override_hours")
            if override is not None:
                try:
                    result[s.scene_number] = float(override)
                    continue
                except (TypeError, ValueError):
                    pass
            result[s.scene_number] = self.estimate_scene(s, ent)["total_hours"]
        return result
