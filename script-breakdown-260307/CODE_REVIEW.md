# Script Breakdown — 代码审查报告

> 审查日期：2026-03-04
> 项目路径：`/Users/wanglaodao/projects/script-breakdown`
> 代码规模：~4,000 行 Python 后端 + ~8,200 行 Python 模块 + ~287 KB 前端 JS + ~129 KB HTML 模板

---

## 一、项目概述

**Script Breakdown（剧本拆解系统）** 是一个影视剧本管理 Web 应用，提供以下核心功能：

| 模块 | 功能 | 入口 |
|------|------|------|
| 剧本解析 | 支持 TXT/DOCX/PDF/FDX 四种格式导入 | `src/parsers/` |
| 场次识别 | 规则引擎 + LLM 双路径检测 | `src/scene/` |
| 实体提取 | 角色、道具、场景类型自动识别 | `src/scene/entity_extractor.py` |
| 排期管理 | CP-SAT 求解器 + LLM 闭环优化 | `src/schedule/` |
| 通告单 | 每日拍摄通告单生成与导出 | `src/callsheet/` |
| 多集管理 | 项目/集数/快照持久化 | `src/web/project.py` |

**技术栈**：Python Flask 后端 + 原生 JavaScript + Jinja2 + TailwindCSS

---

## 二、架构分析

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (Vanilla JS + HTML Templates)                      │
│  app.js (116KB) / panels.js (74KB) / schedule.js / callsheet│
├─────────────────────────────────────────────────────────────┤
│  Flask (app.py — 3999 行单文件)                              │
│  所有 API 路由 + 业务编排 + 异步任务管理                       │
├─────────┬───────────┬────────────┬──────────┬───────────────┤
│ parsers │  scene    │  schedule  │ callsheet│    web        │
│ txt/docx│ detector  │ optimizer  │ generator│  state.py     │
│ pdf/fdx │ patterns  │ constraints│ exporter │  project.py   │
│         │ entities  │ evaluator  │ models   │               │
│         │ llm_det   │ learner    │          │               │
│         │           │ llm_loop   │          │               │
│         │           │ llm_advisor│          │               │
│         │           │ dur_engine │          │               │
├─────────┴───────────┴────────────┴──────────┴───────────────┤
│  LLM Adapters: OpenAI / Claude / Ollama                     │
├─────────────────────────────────────────────────────────────┤
│  Persistence: JSON files (~/.script-breakdown/projects/)     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 架构优点

1. **模块化清晰** — `src/` 下按领域分包（parsers / scene / schedule / callsheet / web / llm），职责明确
2. **LLM 适配层抽象良好** — `BaseLLM` 抽象基类 + 工厂函数 `_create_llm()`，多 provider 统一接口
3. **排期求解分层** — CP-SAT 数学优化 → 贪心回退 → 极端降级，`generate_safe()` 保证永不报错
4. **偏好学习** — `SchedulePreferenceLearner` 通过 EMA 从用户手动调整中学习权重偏好
5. **快照回滚** — 每次排期变更前自动存快照，支持版本对比和恢复

### 2.3 架构问题

#### [严重] `app.py` 过度膨胀 — 3999 行单文件

`app.py` 包含了所有 Flask 路由、业务逻辑编排、异步任务管理、辅助函数。作为一个 4000 行的单文件，严重违反单一职责原则。

**建议**：使用 Flask Blueprint 按领域拆分：
- `routes/upload.py` — 文件上传解析
- `routes/scene.py` — 场次操作
- `routes/schedule.py` — 排期管理
- `routes/callsheet.py` — 通告单
- `routes/project.py` — 项目管理
- `routes/llm.py` — LLM 任务

#### [中等] `AppState` 单例非线程安全

`src/web/state.py` 中的 `AppState` 是进程级单例，但 Flask 开发服务器和异步 `threading.Thread` 共享同一个实例。多个请求并发修改状态（如同时触发排期优化和 LLM 分析）可能导致竞态条件。

```python
# state.py — 问题代码
class AppState:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```

**建议**：
- 对关键状态修改添加 `threading.Lock`
- 或使用 `Flask-SocketIO` / `asyncio` 替代原始线程

#### [中等] 重复的 `import` 和 `import uuid` 在函数内部

`app.py` 中有多处 `import uuid` 和 `import re` 在函数内部进行，例如：

```python
# app.py:1723
import uuid as _uuid
new_id = str(_uuid.uuid4())[:8]
```

**建议**：统一移到文件顶部 import 区域。

---

## 三、模块级代码审查

### 3.1 LLM 适配器 (`src/llm/`)

#### 文件清单
| 文件 | 行数 | 职责 |
|------|------|------|
| `base.py` | 311 | BaseLLM 抽象基类、LLMConfig 数据类 |
| `openai_adapter.py` | 205 | 统一 OpenAI/Claude API 适配 |
| `claude_adapter.py` | 48 | 遗留 Claude 直连适配（可废弃） |
| `ollama_adapter.py` | 67 | 本地 Ollama 适配 |

#### 审查意见

**[良好]** `openai_adapter.py` 统一适配设计

通过 `base_url` 自动检测 API 格式（OpenAI vs Anthropic），避免用户手动选择：

```python
# openai_adapter.py — 自动检测逻辑
if "anthropic" in (self.config.base_url or "").lower():
    # 使用 Anthropic Messages API
else:
    # 使用 OpenAI Chat Completions API
```

**[问题]** `claude_adapter.py` 应标记为废弃

该文件仅 48 行，功能已被 `openai_adapter.py` 完全覆盖。建议标记 `@deprecated` 或删除以避免混淆。

**[问题]** `base.py` 的 LLM prompt 硬编码

`BaseLLM.detect_scenes()` / `summarize_scene()` 等方法中，prompt 模板直接硬编码在类方法里。如果需要支持不同语言或自定义 prompt，需要修改源码。

**建议**：将 prompt 提取为可配置的模板文件或常量模块。

---

### 3.2 解析器 (`src/parsers/`)

#### 文件清单
| 文件 | 行数 | 职责 |
|------|------|------|
| `base.py` | 33 | ParseResult 数据类 + BaseParser 抽象 |
| `txt_parser.py` | 27 | 纯文本解析，自动编码探测 |
| `docx_parser.py` | 87 | Word 文档解析，style-aware |
| `pdf_parser.py` | 103 | PDF 解析，噪声过滤 |
| `fdx_parser.py` | 54 | Final Draft XML 解析 |

#### 审查意见

**[良好]** 编码探测策略

`TxtParser` 使用多编码回退链（utf-8 → gbk → gb2312 → gb18030 → big5 → latin-1），对中文剧本兼容性好：

```python
ENCODINGS = ["utf-8", "gbk", "gb2312", "gb18030", "big5", "latin-1"]
```

**[良好]** PDF 页眉页脚噪声过滤

`PdfParser._detect_noise()` 统计每页头尾行出现频率，40% 以上判定为噪声——实用的启发式方法。

**[问题]** `DocxParser` 表格处理可能导致重复

表格中的段落可能与主体段落重复（Word 文档中表格内文本和正文可共存），当前实现未去重：

```python
# docx_parser.py:42-50 — 表格段落直接追加
for table in doc.tables:
    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                if para.text.strip():
                    _process_para(para)  # 可能与主体段落重复
```

**建议**：维护已处理文本集合进行去重。

**[安全]** FDX 解析使用 `lxml.etree.parse()` 未禁用外部实体

```python
# fdx_parser.py:14
tree = etree.parse(file_path)  # 可能存在 XXE 风险
```

**建议**：使用 `defusedxml.lxml` 或显式禁用外部实体解析：
```python
parser = etree.XMLParser(resolve_entities=False, no_network=True)
tree = etree.parse(file_path, parser)
```

---

### 3.3 场次检测 (`src/scene/`)

#### 文件清单
| 文件 | 行数 | 职责 |
|------|------|------|
| `models.py` | 230 | Scene / SceneList 数据模型 |
| `patterns.py` | 438 | 中英文场次标题正则库 |
| `detector.py` | 207 | 规则引擎场次检测 |
| `entity_extractor.py` | 211 | 角色/道具提取 |
| `llm_detector.py` | 279 | LLM 辅助场次检测 |

#### 审查意见

**[良好]** 正则模式库丰富

`patterns.py` 覆盖了 10+ 种中文场次标题格式（编号式、标签式、斜杠式、方括号式等）和标准英文格式，配合置信度评分，工程化程度高。

**[良好]** 测试覆盖

`tests/test_detector.py` 有 20 个测试用例覆盖中英文模式匹配、场次检测、SceneList 操作（insert_break / merge / remove）。

**[问题]** `entity_extractor.py` 角色名提取依赖硬编码规则

角色提取主要依赖正则和常用称谓词典，对非标准格式剧本可能漏提。建议增加 LLM 辅助提取路径。

**[问题]** `SceneList.merge_scenes()` 缺少边界检查

当合并的 scene 索引超出范围时，当前实现可能抛出 `IndexError` 而非友好错误信息。

---

### 3.4 排期模块 (`src/schedule/`)

#### 文件清单
| 文件 | 行数 | 职责 |
|------|------|------|
| `models.py` | 251 | ShootingDay / ActorSchedule / ScheduleConfig / ProductionSchedule |
| `optimizer.py` | 1056 | CP-SAT 求解 + 级联松弛 + 贪心/极端回退 |
| `duration_engine.py` | 556 | 场景时长估算引擎 |
| `duration_estimator.py` | 58 | 遗留简化时长估算器 |
| `constraints.py` | 261 | 硬约束检查（5 种约束类型） |
| `evaluator.py` | 185 | 目标函数计算 |
| `learner.py` | 294 | EMA 偏好学习 |
| `llm_advisor.py` | 249 | LLM 制片顾问 |
| `llm_loop.py` | 307 | CP-SAT + LLM 闭环优化 |

#### 审查意见

**[优秀]** `optimizer.py` 的 `generate_safe()` 降级策略

四级降级保证永不报错，工程健壮性极高：

```
1. 正常 CP-SAT 求解
2. 放宽工时限制重试
3. 贪心按地点分组
4. 顺序堆叠（兜底）
```

每级失败都记录 warning 传递给前端，用户可了解求解过程。

**[优秀]** `constraints.py` 约束检查设计

5 种约束类型（演员冲突、演员档期、场地可用、每日工时、休息日）分别实现，支持中英文星期映射，`can_add_scene()` 方法支持增量约束检查。

**[优秀]** LLM 闭环优化 (`llm_loop.py`)

CP-SAT → LLM 审查 → 提取约束 → 重新求解的闭环设计，最多 3 轮迭代，LLM 返回结构化 JSON，自动转换为 CP-SAT 约束：

```python
# 支持的 LLM 约束类型
valid_types = {
    "must_before",          # 场次顺序
    "must_same_day",        # 同日拍摄
    "must_different_day",   # 不同日拍摄
    "must_not_date",        # 避开日期
    "prefer_consecutive",   # 连续安排（软约束）
}
```

**[问题]** `duration_estimator.py` 与 `duration_engine.py` 功能重叠

`duration_estimator.py`（58 行）是简化版时长估算器，`duration_engine.py`（556 行）是完整版。两者共存但接口不同，容易混淆。

**建议**：删除 `duration_estimator.py` 或将其标记为废弃。

**[问题]** `optimizer.py` 的 `solve()` 方法递归松弛

`solve()` 通过递归调用自身实现级联松弛（`_relax_level` 参数），最多递归 3 层。虽然有效，但递归深度依赖内部状态，不够直观。

```python
# optimizer.py — 递归松弛
if _relax_level == 0 and extra_constraints:
    sched = self.solve(..., _relax_level=1)  # 递归
```

**建议**：改为循环 + 策略列表，更易读和维护。

**[问题]** `constraints.py` 中工时估算使用固定常量

```python
_MINUTES_PER_SCENE = 45  # 每场 45 分钟固定估算
```

而 `duration_engine.py` 有精确的场景时长估算引擎。`ConstraintChecker` 应使用实际的场景时长数据而非固定值。

---

### 3.5 通告单 (`src/callsheet/`)

#### 文件清单
| 文件 | 行数 | 职责 |
|------|------|------|
| `models.py` | 137 | CastCall / SceneCallInfo / CallSheet 数据模型 |
| `generator.py` | 154 | 通告单生成逻辑 |
| `exporter.py` | 441 | XLSX + Print-ready HTML 导出 |

#### 审查意见

**[良好]** 数据模型一致性

三个 dataclass 都实现了 `to_dict()` / `from_dict()` 序列化，与项目整体风格统一。

**[良好]** HTML 导出的 XSS 防护

`exporter.py` 的 `_h()` 函数对所有用户输入进行 HTML 转义：

```python
def _h(v) -> str:
    return (str(v)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
```

**[问题]** `generator.py` 演员到组时间估算过于简化

当前按固定 30 分钟递增（逆序）：

```python
raw_offset = (reverse_idx + 1) * 30  # 固定 30min 间隔
```

未区分现代妆/古装妆等不同化妆时长。`duration_engine.py` 的表 C 已有相关数据（C1 现代 45min / C2 古装 135min / C3 特效妆 240min），建议引用。

**[问题]** XLSX 导出依赖 `openpyxl` 但未在 `requirements.txt` 中列出

```python
# exporter.py:24 — 运行时导入
import openpyxl
```

`requirements.txt` 中缺少 `openpyxl`，用户调用导出时才会发现缺少依赖。

---

### 3.6 状态与持久化 (`src/web/`)

#### 文件清单
| 文件 | 行数 | 职责 |
|------|------|------|
| `state.py` | 447 | AppState 单例 + undo/redo |
| `project.py` | 448 | Project / EpisodeState / ProjectMeta |

#### 审查意见

**[良好]** Undo/Redo 实现

50 级 undo/redo 栈，每次操作前 `push_undo()` 保存快照：

```python
UNDO_LIMIT = 50
```

**[问题]** `AppState.to_dict()` 序列化可能丢失类型信息

`Scene` 对象通过 `dataclasses.asdict()` 或自定义 `to_dict()` 转换，但跨 API 调用时 `entities` 的键类型（int vs str）不一致：

```python
# app.py:1617 — entities 键混用 int 和 str
e = entities.get(i) or entities.get(str(i)) or {}
```

**建议**：统一 `entities` 的键类型为 `int` 或 `str`，避免双重查找。

**[问题]** JSON 持久化无原子性保证

`project.py` 直接 `json.dump()` 写文件，断电或崩溃时可能产生损坏的 JSON：

```python
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
```

**建议**：先写临时文件再 `os.rename()`（原子操作）：
```python
tmp_path = path + ".tmp"
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp_path, path)
```

---

### 3.7 主应用 (`app.py`)

**行数**：3999 行
**路由数量**：~70+ 个 Flask 路由
**异步任务模式**：`threading.Thread` + 全局字典轮询

#### 审查意见

**[严重] 安全问题 — 文件上传无路径校验**

`/api/upload` 路由接受用户上传文件，但未对文件名进行安全处理。虽然使用 Flask `request.files`（自带 `secure_filename`），但应显式调用并限制上传目录。

**[严重] 安全问题 — 无 CSRF 防护**

所有 POST 路由未使用 CSRF token，在生产环境中存在跨站请求伪造风险。

**建议**：使用 `Flask-WTF` 的 CSRFProtect 或自定义 token 校验。

**[严重] 安全问题 — 无认证鉴权**

所有 API 路由均无认证。虽然当前为本地应用，但如果部署到服务器上，任何人都可以访问和修改数据。

**[问题]** 异步任务状态管理分散

`app.py` 中存在多个独立的全局任务追踪变量：

```python
_llm_classify_status: dict = {}  # LLM 分类任务
state.llm_task                   # 通用 LLM 任务
```

缺少统一的任务管理器，不同类型的异步任务使用不同的追踪机制。

**建议**：抽取 `TaskManager` 类，统一管理所有异步任务的生命周期。

**[问题]** 全局 `import` 在函数内部散落

```python
# app.py:1723 — 函数内部 import
import uuid as _uuid

# app.py:2021-2022 — 函数内部 import
import re
```

**建议**：集中到文件顶部。

---

## 四、前端代码概述

| 文件 | 大小 | 职责 |
|------|------|------|
| `static/js/app.js` | 116KB | 核心应用逻辑、API 调用、事件绑定 |
| `static/js/panels.js` | 74KB | 面板渲染（场次列表、属性、分析） |
| `static/js/schedule.js` | 70KB | 排期管理界面 |
| `static/js/callsheet.js` | 27KB | 通告单界面 |
| `static/css/style.css` | 37KB | 全局样式 |
| `templates/index.html` | 40KB | 主界面模板 |
| `templates/schedule.html` | 44KB | 排期模板 |
| `templates/callsheet.html` | 25KB | 通告单模板 |
| `templates/overview.html` | 20KB | 跨集概览模板 |

### 前端审查要点

**[问题]** 前端 JS 文件过大，无模块化

`app.js`（116KB）和 `panels.js`（74KB）作为单文件未使用任何模块系统（ES modules / bundler），维护困难。

**建议**：迁移到 ES modules + Vite 构建，按功能拆分。

**[问题]** 无前端构建流程

原生 JS + CSS 直接引用，无 minification / tree-shaking / source map。

---

## 五、测试覆盖

| 测试文件 | 测试数 | 覆盖模块 |
|----------|--------|----------|
| `tests/test_detector.py` | 20 | scene.patterns + scene.detector |

### 审查意见

**[严重]** 测试覆盖严重不足

仅有 1 个测试文件覆盖场次检测模块。以下关键模块无任何测试：

- `src/schedule/optimizer.py`（1056 行核心算法，0 测试）
- `src/schedule/constraints.py`（约束检查器，0 测试）
- `src/schedule/evaluator.py`（目标函数，0 测试）
- `src/schedule/learner.py`（偏好学习，0 测试）
- `src/callsheet/generator.py`（通告单生成，0 测试）
- `src/web/state.py`（核心状态管理，0 测试）
- `src/web/project.py`（项目持久化，0 测试）
- `src/llm/openai_adapter.py`（LLM 适配，0 测试）

**建议优先补充测试**：
1. `constraints.py` — 各约束检查的正确性
2. `evaluator.py` — 目标函数计算
3. `optimizer.py` — generate_safe 降级路径
4. `project.py` — 序列化/反序列化一致性

---

## 六、依赖分析

### `requirements.txt` 内容

```
PyQt6>=6.5.0
PyMuPDF>=1.23.0
python-docx>=1.1.0
lxml>=5.0.0
anthropic>=0.40.0
openai>=1.50.0
requests>=2.31.0
flask>=3.0.0
ortools>=9.8
```

### 审查意见

**[问题]** 缺少运行时依赖

以下依赖在代码中使用但未列入 requirements.txt：
- `openpyxl` — XLSX 通告单导出 (`callsheet/exporter.py`)

**[问题]** 不必要的依赖

- `PyQt6>=6.5.0` — 仅用于遗留桌面 UI（`src/ui/`），Web 模式不需要。建议拆分为 `requirements-web.txt` 和 `requirements-desktop.txt`

**[问题]** 依赖版本范围过宽

所有依赖使用 `>=` 下界但无上界，可能导致不兼容升级。建议使用 `~=` 或 `>=X.Y,<Z.0` 约束。

**[问题]** 缺少 `requirements-dev.txt`

没有开发依赖文件（pytest、flake8、mypy 等）。

---

## 七、安全问题汇总

| 等级 | 问题 | 位置 | 建议 |
|------|------|------|------|
| 高 | XXE 注入风险 | `fdx_parser.py:14` | 使用 defusedxml 或禁用外部实体 |
| 高 | 无 CSRF 防护 | `app.py` 全局 | 添加 Flask-WTF CSRFProtect |
| 高 | 无认证鉴权 | `app.py` 全局 | 添加基础认证（至少 token） |
| 中 | 线程竞态条件 | `state.py` AppState | 添加线程锁 |
| 中 | 文件写入非原子 | `project.py` | 先写 tmp 再 rename |
| 低 | Debug 模式硬编码 | `app.py` | 通过环境变量控制 |

---

## 八、性能考量

**[问题]** CP-SAT 求解器默认使用 8 个工作线程

```python
# optimizer.py:516
solver.parameters.num_workers = 8
```

在多用户部署时可能导致 CPU 资源竞争。建议通过配置文件或环境变量控制。

**[问题]** LLM 任务无超时控制

`threading.Thread` 启动的 LLM 任务没有超时机制。如果 LLM API 长时间无响应，任务状态将永远卡在 `running`。

**建议**：添加任务级超时和心跳检测。

**[问题]** 跨集汇总 API 每次全量加载

`/api/projects/summary` 和 `/api/overview/full` 每次请求都遍历所有集数文件：

```python
for ep_id in state.project.meta.episode_order:
    ep = state.project.load_episode(ep_id)  # 每次读文件
```

建议添加缓存或增量更新机制。

---

## 九、代码质量指标

| 指标 | 评级 | 说明 |
|------|------|------|
| 架构设计 | B+ | 模块分层合理，但 app.py 过大 |
| 代码可读性 | B | 中文注释丰富，但部分函数过长 |
| 错误处理 | B+ | LLM 调用有 try-catch，排期有降级 |
| 安全性 | C | 无认证、无 CSRF、XXE 风险 |
| 测试覆盖 | D | 仅 1 个测试文件，关键模块无测试 |
| 依赖管理 | C+ | 依赖不完整，版本约束过松 |
| 可维护性 | B- | 模块清晰但单文件过大，缺少类型注解 |
| 性能 | B | 排期求解有超时控制，但无缓存 |

---

## 十、改进建议优先级

### P0 — 立即处理

1. **修复 XXE 安全漏洞** — `fdx_parser.py` 添加安全的 XML 解析器
2. **补充关键模块测试** — 至少覆盖 constraints / evaluator / project 序列化
3. **添加 `openpyxl` 到 requirements.txt**

### P1 — 短期改进

4. **拆分 `app.py`** — 使用 Flask Blueprint 按领域分包
5. **统一 entities 键类型** — int 或 str 择一
6. **JSON 写入原子性** — 先写 tmp 再 rename
7. **AppState 线程安全** — 添加读写锁

### P2 — 中期优化

8. **前端模块化** — 迁移到 ES modules
9. **删除遗留代码** — `claude_adapter.py`, `duration_estimator.py`, `src/ui/` 桌面 UI
10. **添加 API 认证** — 至少支持 token-based auth
11. **添加 CSRF 防护**
12. **依赖版本约束** — 使用上界限制

### P3 — 长期演进

13. **异步框架迁移** — 考虑 FastAPI + asyncio 替代 Flask + threading
14. **数据库替代 JSON** — 考虑 SQLite 替代 JSON 文件存储
15. **CI/CD 流水线** — 自动测试 + lint + 安全扫描

---

## 十一、各文件代码行数统计

### 后端 Python

| 文件路径 | 行数 |
|----------|------|
| `app.py` | 3999 |
| `main.py` | ~50 |
| `src/llm/base.py` | 311 |
| `src/llm/openai_adapter.py` | 205 |
| `src/llm/claude_adapter.py` | 48 |
| `src/llm/ollama_adapter.py` | 67 |
| `src/parsers/base.py` | 33 |
| `src/parsers/txt_parser.py` | 27 |
| `src/parsers/docx_parser.py` | 87 |
| `src/parsers/pdf_parser.py` | 103 |
| `src/parsers/fdx_parser.py` | 54 |
| `src/scene/models.py` | 230 |
| `src/scene/patterns.py` | 438 |
| `src/scene/detector.py` | 207 |
| `src/scene/entity_extractor.py` | 211 |
| `src/scene/llm_detector.py` | 279 |
| `src/schedule/models.py` | 251 |
| `src/schedule/optimizer.py` | 1056 |
| `src/schedule/duration_engine.py` | 556 |
| `src/schedule/duration_estimator.py` | 58 |
| `src/schedule/constraints.py` | 261 |
| `src/schedule/evaluator.py` | 185 |
| `src/schedule/learner.py` | 294 |
| `src/schedule/llm_advisor.py` | 249 |
| `src/schedule/llm_loop.py` | 307 |
| `src/web/state.py` | 447 |
| `src/web/project.py` | 448 |
| `src/callsheet/models.py` | 137 |
| `src/callsheet/generator.py` | 154 |
| `src/callsheet/exporter.py` | 441 |
| `tests/test_detector.py` | 201 |
| **Python 总计** | **~10,600** |

### 前端

| 文件路径 | 大小 |
|----------|------|
| `static/js/app.js` | 116 KB |
| `static/js/panels.js` | 74 KB |
| `static/js/schedule.js` | 70 KB |
| `static/js/callsheet.js` | 27 KB |
| `static/css/style.css` | 37 KB |
| `templates/index.html` | 40 KB |
| `templates/schedule.html` | 44 KB |
| `templates/callsheet.html` | 25 KB |
| `templates/overview.html` | 20 KB |

---

## 十二、总结

Script Breakdown 是一个功能丰富的影视剧本管理系统，**排期优化模块（CP-SAT + LLM 闭环 + 偏好学习）** 的设计尤为出色。代码整体结构合理，中文注释充分。

**主要风险点**：
1. `app.py` 单文件 4000 行，维护成本高
2. 安全防护缺失（XXE、CSRF、认证）
3. 测试覆盖严重不足（仅 1 个测试文件）
4. 线程安全问题

**突出亮点**：
1. CP-SAT 求解器四级降级策略
2. LLM 闭环排期优化 + 偏好学习
3. 专业领域建模（中文剧本场次格式、影视制片工作流）
4. 时长估算引擎的参数表设计（表 A/B/C）

建议按 P0 → P1 → P2 → P3 的优先级逐步改进，首先解决安全漏洞和测试覆盖问题。
