# Script Breakdown — Claude Code 指南

## 项目概览
影视剧本管理系统，提供剧本拆解（场次识别、实体提取、角色分析）的 Web 应用。

## 技术栈
- **后端**：Python / Flask（入口 `app.py`）
- **前端**：原生 JS + Jinja2 HTML 模板（`static/js/`, `templates/`）
- **LLM**：通过 `src/llm/` 适配器（OpenAI / Claude / Ollama）
- **状态**：`src/web/state.py` — `AppState` 单例
- **持久化**：JSON 文件，路径由 `src/web/project.py` 的 `PROJECTS_DIR` 管理

## 目录结构
```
app.py                  Flask 路由入口
src/
  llm/                  LLM 适配器（base / openai / claude / ollama）
  parsers/              剧本解析器（txt / docx / pdf / fdx）
  scene/                场次检测 + 实体提取
  web/                  AppState、Project 持久化
static/
  css/style.css
  js/app.js             主控逻辑、AppState 前端镜像
  js/panels.js          各面板渲染
templates/
  index.html            主界面
```

## 开发约定
- 路由风格与 `app.py` 现有风格保持一致（`/api/<资源>/<动作>`）
- 前端状态通过 `AppState` 单例管理，不使用全局散变量
- 异步 LLM 任务：`threading.Thread` + 轮询 `/api/llm/status`
- `_create_llm()` 工厂函数统一创建 LLM 实例
- 持久化数据存放在项目目录（`PROJECTS_DIR`）下的 JSON 文件中

## 运行
```bash
python app.py       # 开发服务器
# 或
bash run.command
```

---

## 排期与通告模块开发规范

### 项目背景
这是一个影视剧本管理系统，已完成剧本拆解功能（场次识别、实体提取、角色分析）。现在扩展「排期管理」和「每日通告」两个模块。

### 架构约定
- 后端 Flask，路由风格与 app.py 现有一致
- 前端原生 JS + HTML 模板，风格与 panels.js / app.js 一致
- 状态通过 AppState 单例管理
- 持久化用 JSON 存在项目目录下
- LLM 通过现有 _create_llm() 和 OpenAIAdapter 调用
- 异步任务用 threading.Thread + 轮询 /api/llm/status

### 排期优化算法
三层混合求解：
1. 贪心启发式（按地点分组 + FFD 装箱），< 1秒
2. 模拟退火 + 禁忌搜索（swap/move/block 邻域操作），3-15秒
3. LLM 顾问层（制片人视角建议），10-30秒

目标函数：min Z = α·转场成本 + β·演员成本 + γ·场地成本 + δ·均衡度 + ε·总天数
硬约束：演员不分身、场地可用、每日工时上限、演员档期、休息日

### 动态调整原则
- 已完成的拍摄日冻结不动
- 增量重排：只对受影响的场次子集重新优化
- 每次调整前自动存快照，支持回滚和 diff 对比
