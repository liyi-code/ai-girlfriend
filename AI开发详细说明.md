# 《小念》· 桌面 AI 女友 —— AI 开发详细说明

> 面向开发者 / 技术评委的实现文档。说明整体架构、AI 各能力如何落地、关键难点与扩展方式。
> 架构流程图（7 张 Mermaid）另见 `ARCHITECTURE.md`；玩家视角的功能说明见 `玩家使用指南.md` / `游戏亮点与介绍.md`。

---

## 〇、一句话设计哲学

> **情绪只影响"语气与表情"，性格由情绪长期累计派生并额外驱动"自主行为"，而自主决策只依据习惯/健康信号、绝不读情绪。**

这条红线贯穿所有 AI 模块，是本项目在"情感陪伴"与"安全可控"之间取得平衡的核心。下文每个模块都围绕它展开。

---

## 一、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        桌面层 (Tkinter)                       │
│  半透明输入框 · 设置面板(◐) · 控制台(Ctrl+Alt+G) · 心情面板    │
│  历史弹窗 · 主动关心线程                                       │
└─────────┬───────────────────────────────┬───────────────────┘
          │ 调用 / 信号采集                │ 驱动（socket）
   ┌──────▼─────────┐              ┌───────▼──────────────┐
   │  Assistant     │              │   Live2D 前端         │
   │ (对话/记忆/自主 │              │ (assets/live2d)       │
   │  /情绪/工具)   │◄──socket────►│  pixi + Cubism core   │
   └──┬───┬───┬───┬─┘              └───────────────────────┘
      │   │   │   │
   ┌──┘ ┌─┘ ┌─┘ ┌─┘
   ▼    ▼   ▼   ▼
LLM   Voice  Vision  (外部)
(DeepSeek) (TTS/ASR) (GLM-4V)
```

- **前端表现**：Live2D 由本地 `assets/live2d/index.html`（pixi.js + Cubism core）渲染，Python 端经 **WebSocket/socket** 下发 `{mouth:rms}`、`{talk_stop}`、`expression`、`motion`、`personality` 等指令，驱动口型、表情与动作。
- **后端智能**：`Assistant` 统一编排 LLM、记忆、工具、情绪、自主权限、视觉，是"大脑"。
- **认知注入**：情绪/性格/屏幕/记忆/生活情境以"软信号"方式拼进 system prompt，而非每次都触发。

---

## 二、模块说明（src/ 共 14 个文件）

| 文件 | 职责 |
|---|---|
| `main.py` | 程序入口：初始化各引擎、启动 Live2D 窗口、起主动关心线程、8 秒后后台检查更新、进入 `mainloop` |
| `gui.py` | Tkinter 输入框/设置面板/控制台/心情面板/历史弹窗；注入语音与 Live2D 驱动；主动关心线程；`socket` 调度 |
| `assistant.py` | **核心大脑**：对话编排、确定性动作路由 `_route_action`、系统提示拼装 `system_prompt`、记忆信号采集、运行时换 API、健康护栏 |
| `emotion.py` | **情绪×性格双系统**：5 维情绪 + 性格长期派生 + 注入片段 `prompt_fragment` |
| `autonomy.py` | **受约束自主权限引擎**：事件/信号记录、习惯-健康分析、白名单内自调参、确认/审计/撤销 |
| `memory.py` | 长期记忆读写（`data/memory.json`：偏好/作息/心情/重要日期/历史/画像） |
| `tools.py` | 工具集：开软件/网址、搜文件、跑命令、查状态、看屏、记记忆、调自主、写笔记、查心情 |
| `voice.py` | 语音双链路：TTS（Seed-TTS HTTP）、ASR（本地 faster-whisper）、实时口型 RMS 播放 |
| `vision.py` | 视觉：截图压缩、调用视觉模型、画面级描述；独立 client，可换本地 `llama3.2-vision` |
| `screen_watch.py` | 程序级感知：窗口标题 + 进程名（知道你在玩什么/写什么） |
| `config.py` | 配置解析：相对路径解析、设备自动探测、自主白名单与默认值合并、运行开关 |
| `live2d_app.py` | Live2D 注册表（含 `commercial` 元数据）、模型发现、形象管理 |
| `launcher.py` | 应用启动器（打开软件/网址，供 `tools` 调用） |
| `updater.py` | git-free 自动更新：GitHub tree 比对、原子替换、回滚备份、代理探测 |

> 根目录辅助模块：`seedtts_presets.py`（5 种云端 AI 音色预设）、`live2d_models.py`（模型注册表）、`download_model.py`（拉取 ASR 模型）、`启动.bat`（一键自举 venv/依赖）。

---

## 三、AI 能力实现详解

### 3.1 对话与人格（LLM）

- **模型**：DeepSeek（`deepseek-chat`）经 OpenAI 兼容接口调用；`MODEL` / `OPENAI_BASE_URL` 可在运行时于设置面板/控制台热替换（`Assistant.set_api`，无需重启）。支持任意兼容服务（Ollama / LM Studio 等）。
- **系统提示**：`system_prompt()` 把"温柔女友 + **健康底线**"写死，并动态拼入三块：
  1. `emotion.prompt_fragment()` —— 当前**性格人格描述 + 主导情绪**；
  2. `(memory.profile_text())` —— 已记住的关于用户的一切；
  3. 工具使用规则与"健康底线·最重要"约束（识别爆肝/熬夜必须优先劝导，绝不迎合）。
- **健壮性**：缺 Key 不崩——`__init__` 容忍 `sk-no-key`，`chat()` 入口检查无 Key 时返回友好提示；`deepseek-r1` 等推理模型带 `<think>` 标签时由 `_strip_think()` 剥离；工具不可用时有"退化纯对话"兜底。

### 3.2 记忆系统

- `memory.py` 持久化到 `data/memory.json`，跨会话保留，含偏好/作息/心情/重要日期/历史/画像。
- `assistant._maybe_record_signals(user_text)` 每次聊天抽取健康/习惯线索喂给自主引擎；模型侧通过 `remember` 工具把"用户透露的偏好/作息/心情"记下来。
- `screen_watch` 提供程序级上下文（在玩什么游戏/写什么文档），作为记忆补充。

### 3.3 主动关怀

- 定时线程（默认 `PROACTIVE_INTERVAL_MIN`，约 15–30 分钟）触发 `gui.on_event` → `autonomy.record_event`。
- 结合记忆判断深夜/久坐/爆肝，由 `autonomy.analyze()` 生成关怀话术并弹窗；**健康护栏**确保"劝导优先于迎合"。
- 这是把"等待输入"变成"双向陪伴"的关键——她会主动惦记你。

### 3.4 情绪 × 性格双系统（emotion.py）★核心 AI

这是小念"有温度"的来源，也是设计最细的一块。职责严格分离：

**① 情绪（`EmotionEngine`，5 维短期波动）**
- 维度：`joy`（喜）/ `anger`（怒）/ `sadness`（哀）/ `calm`（平静）/ `anxiety`（不安）。
- `perceive(text=None, event=None, source, delta)` 经 `_perceive_rules` 更新各维权重；`decay()` 随时间自然衰减，`_clamp()` 约束边界。
- `dominant()` 取当前主导情绪；`voice_tone()` 给语音合成提供声调偏置；`snapshot()` / `describe()` 供心情面板可视化。
- **情绪只影响两件事**：聊天语气（`prompt_fragment` 含主导情绪）+ Live2D 表情/动作/语音声调。**绝不参与自主决策**。

**② 性格（由情绪长期累计派生）**
- `analyze_personality()` 把历史情绪累计，映射成 5 类性格底色（温柔平静 / 活泼开心 / 傲娇小脾气 / 敏感爱哭 / 黏人紧张）。
- 性格访问接口（供其他模块取用）：
  - `personality_trait()`：当前性格类别；
  - `personality_emo_bias()`：性格对情绪池的偏置；
  - `personality_behavior()`：行为偏好（如"大动作跳/转身"概率）；
  - `personality_autonomy_tone()`：自主提示的性格化语气；
  - `personality_comfort_base()`：关怀暖度下限（autonomy 引用抬高下限）。
- **性格额外驱动自主行为与话术**：`autonomy` 注入性格关怀下限 + toast 性格语气；`gui` 下发性格到 Live2D 前端 `playMotion` 融合选动作。

> 设计红线落点：情绪是"当下心情"，性格是"长期关系底色"。情绪不参与"她该不该自己做主"——那是 autonomy 的职责，只认习惯/健康信号。

### 3.5 受约束自主权限（autonomy.py）★核心创新

把"AI 该不该自己做主"做成**可玩、可控、可审计**的机制。

- **白名单**：`AUTONOMY_WHITELIST` 限定 7 类无害配置（提醒频率、语气暖度、鼓励动作开关等）。
- **写入隔离**：小念只能在白名单内改 `data/autonomy_overrides.json`，**结构上无权碰系统/代码/用户文件**；每次改动 `_backup_overrides()` 自动 `.bak` 备份 + `_audit()` 审计日志。
- **大调整确认**：作息/设备类改动 `_needs_confirm()` 命中 → `_ask_confirm()` 弹窗；用户可同意或拒绝；越界值 `_clamp` 钳回安全范围。
- **健康护栏**：`analyze()` 规则只往"更频繁提醒休息 / 更温柔鼓励 / 打开备份"方向调；识别熬夜/爆肝优先劝导不迎合。
- **关键设计**：`analyze()` **只依据习惯/健康信号**，不读 `emotion`——避免被情绪带偏（详见 §0 红线）。
- 透明与可逆：工具 `review_my_changes` / `set_autonomy` / `tune_my_setting` 让玩家随时查看、开关、收回；控制台可一键 `reset_all()`。

### 3.6 语音：TTS + ASR + 实时口型

- **TTS（输出）**：`voice.py` 向字节 Seed-TTS 服务 `POST` 文本 + 音色预设（5 种：清冷御姐/屑御姐/可爱萝莉/正太/成男），返回音频字节；用 `av` 解码 MP3，经 `OutputStream` 回调播放。
- **ASR（输入）**：本地 `faster-whisper-small` 离线推理，**无需 API Key、无需联网**（`_load_whisper` 优先用本地 `models/` 目录，离线稳定）。
- **实时口型（关键难点）**：播放回调里取"当前正在播放音频片"的 **RMS 能量**存入共享变量；泵线程按 ~0.07s 间隔读最新值，经 socket 发 `{mouth:rms}` → 前端 `setMouth` 映射 `ParamMouthOpenY`（自适应峰值归一化 + 30% 平滑）；结束发 `{talk_stop}` 归零。**严格对齐实际播放**，句尾拖音也对得齐（已修声卡缓冲漂移 bug）。

### 3.7 视觉看屏（vision.py）

- `capture()` 用 `PIL.ImageGrab` 截主屏 → 等比缩到 `VISION_MAX_WIDTH`(1280) → JPEG q80，存 `data/screen_watch/`。
- `look()` / `describe_screen()` 调视觉模型（GLM-4V 默认，可换本地 `llama3.2-vision`），把画面事实拼进正反馈；任何失败优雅降级返回 `None`。
- **与程序级感知区分**：程序级=知道开哪个软件（窗口标题/进程名）；视觉级=看懂画面内容（输赢/报错/文档/视频封面）。两者层次不同，前端可叠加。

### 3.8 Live2D 形象、水印与情绪自适应动作

- **注册表**：`live2d_models.py` 支持多模型（含 `commercial` 元数据）；GUI 形象管理（`Ctrl+Alt+O`）可切换/新增。默认官方免费**可商用**「桃濑日和-PRO」。
- **水印隐藏**：官方模型水印由 `Param191` 控制（=1 隐藏）；在 `beforeModelUpdate` + `afterMotionUpdate` 双钩子每帧 `setParameterValueById("Param191",1)`，任何表情/动作都盖不掉。
- **情绪自适应动作**：前端 `playMotion` 把每个动作/表情的"组名+文件名+表情名"做中英文关键词匹配，归入 5 个情绪池（喜/怒/哀/静/怯）；说话时按当前情绪+性格融合选动作。要点：**动作组/表情名带情绪关键词**（如 `开心.motion3.json`/`害羞.motion3.json`）才能触发真正自适应；否则退化为通用随机插播。

### 3.9 工具集（tools.py）

所有工具以 `@tool(schema)` 装饰注册，`execute_tool(name, args, memory)` 统一分发。明确动作走 `assistant._route_action` 的**确定性正则路由**（保证"说打开就打开、说搜就真搜"，不依赖模型是否主动调工具）：

| 工具 | 触发方式 | 作用 |
|---|---|---|
| `open_application` | `_OPEN_RE`（"打开/启动…"） | 打开本地软件 |
| `open_website` | 同上，识别 URL/别名 | 打开网页 |
| `search_files` | `_SEARCH_RE`（"搜/找…文件"） | 按名检索文件 |
| `run_command` | 模型/显式 | 执行命令（仅在信任环境） |
| `get_system_status` | `_STATUS_RE` | 内存/CPU/配置 |
| `look_at_screen` | `_SCREEN_RE`（"看看我的屏幕…"） | 截图+视觉理解 |
| `remember` | 模型/显式 | 写入长期记忆 |
| `set_autonomy` | `_AUTONOMY_ON/OFF_RE` | 开关自主权限 |
| `tune_my_setting` | 模型/显式 | 白名单内调参 |
| `review_my_changes` | `_AUTONOMY_REVIEW_RE` | 查看自主改动 |
| `create_text_file` | 模型/显式 | 写计划/清单/笔记到"小念工作台" |
| `feelings_status` | 显式/面板 | 当前心情与性格快照 |

路由优先级：打开/网址 > 搜索文件 > 系统状态 > 看屏幕 > 自主开关/审查。

### 3.10 运行时换 API（无需重启）

- 对话：`Assistant.set_api(api_key, base_url, model)` 更新 `CONFIG` 并重建 OpenAI 客户端；语音 ASR 的 openai 分支在调用时实时读 `CONFIG`，自动跟随。
- 视觉：`vision.set_vision_api(...)` 重置 `_client` 缓存。
- 保存：`_write_env_value` 把改动写回 `.env`（保留其它行/注释），下次启动仍生效。GUI 的"测试连接"用 8 token 探针在线程验证。

---

## 四、关键技术难点与解决方案

| 难点 | 现象 | 解决方案 |
|---|---|---|
| 口型句尾漂移 | 用 `time.time()` 预计算能量时间轴驱动口型，与声卡缓冲漂移，句尾嘴停 | 改为在播放回调取"当前发声片 RMS"存共享变量，泵线程读最新值发出，严格对齐实际播放 |
| Live2D 水印 | `getParameterCount` 不存在导致旧方案失效、水印常显 | 收集候选 core 对象，每帧双钩子强制 `Param191=1` |
| 跨电脑部署 | 绝对路径/写死 cuda/缺 venv 起不来 | 相对路径解析 + 设备自动探测 + `启动.bat` 一键自举 |
| ASR 离线稳定 | HuggingFace 国内被墙、模型下不全 | 本地 `models/` 内置权重优先；`download_model.py` 走 `hf-mirror.com` 镜像 + 断点续传 |
| 滚轮失效 | Canvas `yscrollincrement=0` 时 `units` 模式只滚 1px | 设 `yscrollincrement=1` + 步长放大到 `delta/3` + 延迟刷新 `scrollregion` |
| 推理模型噪声 | `deepseek-r1` 返回含 `<think>` 思考链 | `_strip_think()` 剥离，避免被念出/显示 |
| 视觉测试误报 | 1×1 PNG 被智谱拒收报 400 | 测试按钮改用真实截图（PIL.ImageGrab）验证，避免误导 |

---

## 五、性能与瓶颈

- 端到端延迟：ASR(CPU small ~3s) + LLM(~3s) + TTS(云端 ~数秒)。
- 语音识别本地 CPU 推理；TTS 走云端（需网络）；对话/视觉需各自 API Key。
- 已优化：口型与音频严格对齐、视觉失败降级、记忆读写轻量（本地 JSON + 滑动窗口 `recent_history(20)`）。
- 想更跟手：LLM 可换 `qwen2.5:14b` / `llama3.1:8b` 等更小模型，或在本地 Ollama 全离线。

---

## 六、扩展指南

1. **换对话模型**：`.env` 改 `OPENAI_BASE_URL` / `MODEL`，或 GUI 运行时热替换（`set_api`）。
2. **加 Live2D 形象**：把模型放 `assets/live2d/`，在 `live2d_models.py` 注册（标 `commercial=True`）；情绪自适应需动作/表情名带情绪关键词。
3. **加工具**：用 `@tool(schema)` 在 `tools.py` 注册函数，并在 `assistant._route_action` 增加正则路由（或依赖模型调 `execute_tool`）。
4. **调自主权限**：`config.py` 的 `AUTONOMY_WHITELIST` 增删条目，越界自动钳制；改 `autonomy.analyze()` 规则方向。
5. **调情绪/性格**：`emotion.py` 的 `_perceive_rules` / `analyze_personality` / `personality_*` 接口；前端 `index.html` 的 `playMotion` 情绪池关键词。
6. **离线对话**：接入本地 OpenAI 兼容服务（Ollama / LM Studio）即可完全离线。

---

## 七、部署与运行

```bash
# 1. 安装 Python 3.10 ~ 3.14（勾选 Add to PATH）
# 2. 双击 启动.bat：自动建 venv、装依赖、生成 .env、下载 ASR 模型（国内镜像/断点续传）
# 3. 填钥匙：启动后 ◐ → API 设置 填 Key/URL/模型 → 测试连接 → 保存应用
# 4. 再次双击 启动.bat 启动（或 python -m src.main）
```

- 语音识别模型已内置，离线可用；语音输出与对话/视觉需自备 Key。
- 个人数据（`data/`、`.env`）不入库，分发安全。
- 便携版已接入 `updater.py`：启动 8 秒后后台静默比对 GitHub tree，差异先备份后原子替换，失败回滚。

---

## 八、版权与合规（参赛要点）

| 资源 | 来源 | 授权 |
|---|---|---|
| Live2D「桃濑日和-PRO」 | 官方示例模型 | 免费可商用 |
| 语音音色 | 字节 Seed-TTS 云端 AI 生成（非克隆真人） | 无真人 IP 风险 |
| 对话大模型 | DeepSeek（可换任意 OpenAI 兼容） | 用户自备 Key |
| 视觉理解 | 智谱 GLM-4V（可换本地） | 用户自备 Key |
| 语音识别 | 本地 faster-whisper | 离线 · 免费 · 开源 |

> 全链路**不克隆任何真人/角色音色**，规避常见 IP 隐患，适合公开发布与参赛。

---

*技术栈：Python · Tkinter · Live2D(Cubism 2/3/4) · DeepSeek · 字节 Seed-TTS · faster-whisper · 智谱 GLM-4V · WebSocket/socket*
