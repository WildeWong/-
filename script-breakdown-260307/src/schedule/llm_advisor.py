"""LLM-based schedule advisor for production planning (排期顾问)."""
from __future__ import annotations


_RISK_LABELS: dict[str, str] = {
    "rain":                 "下雨 / 恶劣天气",
    "actor_sick":           "主演生病 / 临时缺席",
    "location_unavailable": "拍摄地点临时不可用",
    "overtime":             "严重超时 / 进度滞后",
}

_SYSTEM_ANALYZE = (
    "你是一位有 20 年经验的影视制片主任（Line Producer）。"
    "你对拍摄排期有深刻理解，熟悉场次分组、演员档期管理、转场效率和制作成本控制。"
    "请根据提供的排期信息，从专业角度给出简明实用的优化建议。"
    "回答用中文，以编号列表形式，每条建议独立成段，直接切入问题。"
)

_SYSTEM_DAY = (
    "你是一位经验丰富的导演助理，负责制定每日拍摄顺序。"
    "你熟悉以下原则：利用自然光、减少演员化妆转换次数、"
    "遵循情绪递进逻辑、先拍重场次留足状态。"
    "请根据提供的场次信息，给出当天最优的拍摄顺序建议。"
    "用中文回答，格式为编号列表，附简短理由。"
)

_SYSTEM_NOTES = (
    "你是一位经验丰富的制片，擅长从剧本内容中预判拍摄难点和特殊需求。"
    "请仔细阅读以下场次剧本内容，生成一份简明的拍摄注意事项清单。"
    "重点关注：特殊道具、特效/危险动作、大量群演、动物、特殊场地许可、"
    "高难度情感表演、持续多天的连续场次等。"
    "用中文，以分类列表形式输出，无需则写「无特殊要求」。"
)

_SYSTEM_TRADEOFF = (
    "你是资深影视制片人，擅长从成本、效率、风险三个维度权衡不同排期方案。"
    "请客观分析两个方案的利弊，给出有据可查的推荐意见。"
    "用中文，语言简明直接，避免模糊表述。"
)

_SYSTEM_CONTINGENCY = (
    "你是资深影视制片人，专长风险预判与应急预案制定。"
    "你了解剧组实际运作：临时调整场次、演员替换、转移拍摄地点等常规应对手段。"
    "请给出可立即执行的具体预案，而非泛泛的原则性建议。"
    "用中文，以结构化列表输出。"
)

_SYSTEM_ACTOR_WORKLOAD = (
    "你是演员档期与工作量顾问，负责从演员权益和拍摄质量两个角度评估工作强度。"
    "判断标准：连续工作天数、单日场次数量、情感强度累积、是否有足够休息间隔。"
    "用中文，给出量化描述（如：「连续 X 天高强度戏份」），并给出具体调整建议。"
)


class LLMScheduleAdvisor:
    """Wraps a BaseLLM instance to provide schedule-specific analysis methods."""

    def __init__(self, llm):
        """
        Args:
            llm: A BaseLLM instance created via _create_llm(config).
        """
        self.llm = llm

    # ── Public methods ────────────────────────────────────────────────

    def analyze_schedule(self, schedule_summary: str, constraints_summary: str) -> str:
        """From a producer's perspective, analyse the current schedule.

        Checks:
        1. Illogical arrangements (e.g. emotional scene after heavy action)
        2. Actor work-density balance
        3. Transition / location-change efficiency
        4. Specific, actionable optimisation suggestions

        Args:
            schedule_summary:   Human-readable summary of all shooting days,
                                scenes, actors and locations.
            constraints_summary: Known constraints (actor availability,
                                location costs, existing conflicts).
        Returns:
            LLM analysis text (Chinese, numbered list).
        """
        prompt = (
            "## 当前排期摘要\n\n"
            f"{schedule_summary}\n\n"
            "## 已知约束与冲突\n\n"
            f"{constraints_summary}\n\n"
            "## 分析要求\n\n"
            "请从制片主任角度逐一检查以下四个维度，给出 **具体可落地** 的优化建议：\n"
            "1. **场次安排合理性** — 情绪戏、动作戏的衔接是否合理？重场次是否放在最佳时段？\n"
            "2. **演员工作密度** — 主演连续工作天数、密集场景是否过载？有无成本节约空间？\n"
            "3. **转场效率** — 同一天内地点切换次数、转场时间是否可以进一步压缩？\n"
            "4. **整体风险** — 是否存在进度风险、成本风险或调度瓶颈？如何应对？\n\n"
            "最后给出 **优先级最高的 3 条** 立即可执行的调整动作。"
        )
        return self.llm.complete(prompt, _SYSTEM_ANALYZE).strip()

    def suggest_day_arrangement(self, scenes_for_day: str) -> str:
        """Suggest the optimal shooting order for a single day.

        Considers: natural light changes, actor makeup/costume transitions,
        emotional progression, and saving the hardest takes for peak energy.

        Args:
            scenes_for_day: Formatted description of all scenes planned for
                            the day (scene number, location, type, actors,
                            synopsis, etc.).
        Returns:
            LLM suggestion text (Chinese, numbered order with brief reasons).
        """
        prompt = (
            "## 本日待拍场次\n\n"
            f"{scenes_for_day}\n\n"
            "## 任务\n\n"
            "请为以上场次安排最优的当日拍摄顺序，并说明每步调整的理由。\n"
            "考虑因素（按重要性排序）：\n"
            "- 自然光利用（外景优先在特定时段）\n"
            "- 演员化妆 / 造型切换次数最少\n"
            "- 情绪递进逻辑（从轻松到沉重，或根据剧情需要反向）\n"
            "- 场地转移时间（相同地点场次连续拍摄）\n"
            "- 把最难的情感场次安排在演员状态最佳时\n\n"
            "输出格式：\n"
            "1. 场次X — [简要理由]\n"
            "2. 场次X — [简要理由]\n"
            "...\n\n"
            "最后附一句「导演提示」说明全天节奏安排的总体思路。"
        )
        return self.llm.complete(prompt, _SYSTEM_DAY).strip()

    def generate_notes(self, scene_content: str) -> str:
        """Generate production notes from scene script content.

        Flags: special props, VFX/stunts, crowd scenes, animals,
        permits, demanding emotional performances, multi-day continuity.

        Args:
            scene_content: Raw script text for the scene(s).
        Returns:
            Production notes checklist (Chinese, categorised list).
        """
        prompt = (
            "## 场次剧本内容\n\n"
            f"{scene_content}\n\n"
            "## 任务\n\n"
            "请从以下类别生成拍摄注意事项清单（无相关项则跳过该类别）：\n\n"
            "**【特殊道具】** 需要提前采购或制作的关键道具\n"
            "**【特效/危险动作】** 烟火、爆破、高空、水下、替身需求\n"
            "**【群演需求】** 需要多少群演，是否需要造型/服装协调\n"
            "**【动物/儿童】** 相关法规和协调需求\n"
            "**【场地/许可】** 需要提前申请的拍摄许可或特殊场地准备\n"
            "**【情感/表演难度】** 高强度情感场次，演员需要额外准备时间\n"
            "**【连续性】** 与前后场次的服装/化妆/道具连续性要求\n"
            "**【其他风险】** 任何其他可能影响拍摄进度的因素"
        )
        return self.llm.complete(prompt, _SYSTEM_NOTES).strip()

    def evaluate_trade_off(self, option_a_summary: str, option_b_summary: str) -> str:
        """Compare two schedule options and recommend one from a producer's perspective.

        Useful when the user is torn between two manual arrangements and wants
        an AI second opinion on cost, risk, and practical considerations.

        Args:
            option_a_summary: Human-readable description of schedule option A.
            option_b_summary: Human-readable description of schedule option B.
        Returns:
            LLM comparison and recommendation text (Chinese).
        """
        prompt = (
            "你是制片人。以下是两个排期方案，请比较它们的优劣：\n\n"
            "## 方案 A\n\n"
            f"{option_a_summary}\n\n"
            "## 方案 B\n\n"
            f"{option_b_summary}\n\n"
            "## 分析要求\n\n"
            "请从以下三个维度分别分析两个方案，然后给出最终推荐：\n\n"
            "**1. 各自的优势和风险**\n"
            "   - 方案 A 的核心优势 / 潜在风险\n"
            "   - 方案 B 的核心优势 / 潜在风险\n\n"
            "**2. 成本差异估算**\n"
            "   - 演员档期成本（连续天数、等待时间）\n"
            "   - 场地/转场成本（地点切换次数、距离）\n"
            "   - 进度风险成本（哪个方案风险更高）\n\n"
            "**3. 推荐结论**\n"
            "   - 明确推荐哪个方案（A 或 B）\n"
            "   - 核心理由（2-3 条，具体可执行）\n"
            "   - 如果推荐方案有缺点，说明如何弥补\n"
        )
        return self.llm.complete(prompt, _SYSTEM_TRADEOFF).strip()

    def suggest_contingency(self, current_schedule_summary: str, risk_type: str) -> str:
        """Generate a contingency plan for a given risk scenario.

        Args:
            current_schedule_summary: Human-readable summary of the current schedule.
            risk_type: One of "rain" | "actor_sick" | "location_unavailable" | "overtime".
                       Unknown values are passed through as-is.
        Returns:
            Contingency plan text (Chinese, structured list).
        """
        risk_label = _RISK_LABELS.get(risk_type, risk_type)
        prompt = (
            "你是制片人。当前排期如下：\n\n"
            f"{current_schedule_summary}\n\n"
            f"## 风险场景：{risk_label}\n\n"
            "请为上述风险制定详细的应急预案，覆盖以下三个部分：\n\n"
            "**1. 最易受影响的拍摄日 / 场次**\n"
            "   - 列出具体日期和场次编号\n"
            "   - 说明为什么这些日子风险最高\n\n"
            "**2. 推荐的备选安排**\n"
            "   - 具体到场次调换建议（哪些场次可以前移 / 后移 / 替换）\n"
            "   - 若涉及演员缺席，说明哪些场次可以不需该演员先拍\n"
            "   - 若涉及场地，说明可以临时替换到哪些类似场地\n\n"
            "**3. 提前准备事项**\n"
            "   - 需要预约或确认的资源（备用场地、替身演员、备用道具等）\n"
            "   - 需要提前与哪些部门沟通协调\n"
            "   - 建议触发预案的判断时间节点\n"
        )
        return self.llm.complete(prompt, _SYSTEM_CONTINGENCY).strip()

    def analyze_actor_workload(self, schedule_summary: str, actor_name: str) -> str:
        """Analyse a specific actor's workload and flag over-scheduling risks.

        Args:
            schedule_summary: Human-readable summary of the full schedule
                              (should include per-day scene and actor info).
            actor_name: Character name (角色名) of the actor to analyse.
        Returns:
            Workload analysis and recommendations (Chinese).
        """
        prompt = (
            f"你是制片人，请分析角色「{actor_name}」在以下排期中的工作强度：\n\n"
            f"{schedule_summary}\n\n"
            "## 分析要求\n\n"
            "**1. 工作强度概览**\n"
            f"   - 「{actor_name}」共出现在哪些拍摄日？总天数？\n"
            "   - 最长连续工作天数？连续工作期间是否有高强度情感戏？\n"
            "   - 单日最多同时拍摄几个场次？\n\n"
            "**2. 风险点识别**\n"
            "   - 是否存在连续高强度安排（连续 5 天以上 / 单日超过 4 个场次）？\n"
            "   - 情感密集场次是否集中在连续几天，没有缓冲日？\n"
            "   - 是否有跨越凌晨的拍摄安排（夜戏接日戏）？\n\n"
            "**3. 调整建议**\n"
            "   - 如果存在过载风险，具体建议哪些场次可以分散到其他日期\n"
            "   - 如果整体合理，说明当前安排的优点\n"
            "   - 给出 1-2 条最优先的改进建议\n"
        )
        return self.llm.complete(prompt, _SYSTEM_ACTOR_WORKLOAD).strip()
