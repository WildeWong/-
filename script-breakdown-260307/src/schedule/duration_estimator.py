"""场次拍摄时长估算器 — 基于剧本行数和场景属性"""
from __future__ import annotations

from typing import Any


class SceneDurationEstimator:
    TYPE_FACTOR: dict[str, float] = {
        "对话": 0.8, "文戏": 0.8,
        "动作": 1.8, "武打": 1.8, "打斗": 1.8,
        "情感": 1.2, "哭戏": 1.2,
        "群戏": 1.5, "群演": 1.5,
        "特效": 2.0, "爆破": 2.0,
        "过场": 0.5, "旁白": 0.5,
    }

    def __init__(self, scenes: list[Any], entities: dict[int, dict]) -> None:
        self.scenes = scenes
        self.entities = entities

    def estimate_all(self) -> dict[int, float]:
        """返回 {scene_number: hours}"""
        return {s.scene_number: self._one(s) for s in self.scenes}

    def _one(self, scene: Any) -> float:
        ent = self.entities.get(scene.scene_number, {})
        lines = max(getattr(scene, 'end_line', 0) - getattr(scene, 'start_line', 0), 3)
        pages = lines / 55.0
        base = pages * 50.0 / 60.0  # 每页50分钟

        # 类型系数
        stype = str(ent.get("scene_type", "") or "")
        tf = 1.0
        for kw, f in self.TYPE_FACTOR.items():
            if kw in stype:
                tf = f
                break

        # 内外景系数（精确匹配避免"内外"同时含"外"的误判）
        int_ext = (getattr(scene, 'int_ext', '') or '').strip()
        ef = 1.3 if int_ext == '外' or int_ext.startswith('外') else 1.0

        nf = 1.2 if "夜" in (getattr(scene, 'time_of_day', '') or '') else 1.0
        cast = len(ent.get("characters", []))
        cf = 1.3 if cast >= 6 else (1.1 if cast >= 3 else 1.0)

        return round(max(0.25, min(8.0, base * tf * ef * nf * cf)), 2)

    def summary(self) -> dict:
        d = self.estimate_all()
        v = list(d.values())
        t = sum(v)
        return {
            "total_hours": round(t, 1),
            "avg": round(t / max(len(v), 1), 2),
            "min_days_12h": max(1, -(-int(t) // 12)),  # ceil division
            "durations": d,
        }
