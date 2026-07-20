# 《小念》· 桌面 AI 女友 —— AI 开发详细说明

> 面向开发者 / 评委的技术文档。说明系统架构、AI 能力实现、关键技术难点与扩展方式。

---

## 一、系统架构

```
┌─────────────────────────────────────────────────────────┐
│                        桌面层 (Tkinter)                    │
│  半透明输入框 · 设置面板(◐) · 控制台(Ctrl+Alt+G) · 历史    │
└───────────────┬───────────────────────────┬──────────────┘
                │ 调用                        │ 驱动
        ┌───────▼────────┐          ┌─────────▼──────────┐
        │  Assistant     │          │   Live2D 前端        │
        │ (对话/记忆/自主)│          │ (assets/live2d)      │
        │  + tools       │◄─socket─►│  pixi + Cubism core  │
        └───┬───┬───┬───┘          └──────────────────────┘
            │   │   │
   ┌────────┘   │   └────────┐
   ▼            ▼            ▼
LLM(DeepSeek)  Voice       Vision(GLM-4V)
               TTS(Seed-TTS)
               ASR(faster-whisper,本地)
```

- **前端表现**：Live2D 通过本地 `assets/live2d/index.html`（pixi.js + Cubism core）渲染，Python 端经 **WebSocket/socket** 发送 `{mouth:rms}`、`{talk_stop}`、`expression`、`motion` 等指令驱动口型与动作。
- **后端智能**：`Assistant` 统一编排 LLM、记忆、工具、自主权限、视觉。

---

## 二、模块说明（src/）

| 文件 | 职责 |
|---|---|
| `main.py` | 程序入口，初始化各模块并启动 GUI 主循环 |
| `gui.py` | Tkinter 输入框/设置面板/控制台/历史弹窗；注入语音与 Live2D 驱动；滚轮滚动容器 |
| `assistant.py` | 核心：对话编排、系统提示、记忆信号采集、工具路由、自主权限注入、运行时换 API |
| `memory.py` | 长期记忆读写（`data/memory.json`：偏好/作息/心情/重要日期/历史） |
| `autonomy.py` | 受约束自主权限引擎：事件记录、信号分析、白名单内自调参、审计日志、确认/撤销 |
| `tools.py` | 工具集：开应用/搜文件/跑命令/建文件/看屏/自主调参/查看历史 |
| `voice.py` | 语音双链路：TTS（Seed-TTS HTTP）、ASR（本地 faster-whisper）、实时口型 RMS 播放 |
| `vision.py` | 视觉：截图压缩、调用视觉模型、画面级描述；独立于对话 client |
| `screen_watch.py` | 程序级感知：窗口标题 + 进程名（知道你在玩什么/写什么） |
| `config.py` | 配置解析：相对路径解析、设备自动探测、自主白名单与默认值合并 |
| `live2d_app.py` | Live2D 模型注册表（含 license/commercial 元数据）、形象管理 |
| `launcher.py` | 启动引导（与 `启动.bat` 配合） |

---

## 三、AI 能力实现详解

### 3.1 对话与人格（LLM）
- 模型：DeepSeek（`deepseek-chat`），通过 OpenAI 兼容接口调用；`MODEL`/`BASE_URL` 可在运行时于 GUI 切换（无需重启）。
- 人格：系统提示写入"温柔女友 + 健康底线"，并把**记忆摘要**、**屏幕事实**、**自主偏好**拼进上下文，让回复个性化。
- 工具调用：模型可返回结构化动作，由 `_route_action` 用关键词确定性路由（避免模型不主动调工具），如"看看我的屏幕"→ 视觉工具。

### 3.2 记忆系统
- `memory.py` 持久化到 `data/memory.json`，跨会话保留。
- `assistant._maybe_record_signals` 在每次聊天中抽取偏好/作息/心情信号写入记忆；`screen_watch` 提供程序级上下文。

### 3.3 主动关怀
- 定时线程（默认 30 分钟）触发 `on_event` → `autonomy.record_event`；
- 结合记忆判断是否深夜/久坐/爆肝，生成关怀话术并弹窗；健康护栏确保"劝导优先于迎合"。

### 3.4 受约束自主权限（核心创新）
- `AUTONOMY_WHITELIST` 限定 7 类无害配置（如提醒频率、语气暖度、鼓励动作开关）；
- 小念只能在白名单内改 `data/autonomy_overrides.json`，每次改动自动 `.bak` 备份 + 审计日志；
- 大调整（作息/设备类）走 `request_confirm` 弹窗确认；越界改动被钳制回安全范围；
- `analyze()` 规则只往"更频繁提醒休息 / 更温柔鼓励 / 打开备份"方向调，结构上无权碰系统/代码/用户文件。

### 3.5 语音：TTS + ASR
- **TTS（输出）**：`voice.py` 向字节 Seed-TTS 服务 `POST` 文本 + 音色预设（5 种），返回音频字节；用 `av` 解码 MP3，经 `OutputStream` 回调播放。
- **ASR（输入）**：本地 `faster-whisper-small` 离线推理，**无需 API Key、无需联网**（模型已内置 `models/`）。`voice.py::_load_whisper` 优先用本地模型目录，离线稳定。
- **实时口型（关键）**：播放回调里取"当前正在播放音频片"的 RMS 能量存入共享变量；泵线程按 ~0.07s 间隔读最新值，经 socket 发 `{mouth:rms}` → 前端 `setMouth` 映射 `ParamMouthOpenY`（自适应峰值归一化 + 30% 平滑）。结束发 `{talk_stop}` 归零。

### 3.6 视觉看屏
- `vision.py::capture()` 用 `PIL.ImageGrab` 截主屏 → 等比缩到 `VISION_MAX_WIDTH`(1280) → JPEG q80；
- `look()` / `describe_screen()` 调视觉模型（GLM-4V），把画面事实拼进正反馈；任何失败优雅降级返回 `None`。
- 与"程序级感知"区分：程序级=知道开哪个软件；视觉级=看懂画面内容（输赢/报错/文档）。

### 3.7 Live2D 形象与水印
- 形象注册表 `live2d_models.py` 支持多模型（含 `commercial` 元数据），GUI 形象管理对话框可切换/新增。
- **水印隐藏**：官方模型水印由 `Param191` 控制（=1 隐藏）；在 `beforeModelUpdate` + `afterMotionUpdate` 双钩子每帧 `setParameterValueById("Param191",1)`，任何表情/动作都盖不掉。

---

## 四、关键技术难点与解决方案

| 难点 | 现象 | 解决方案 |
|---|---|---|
| 口型句尾漂移 | 用 `time.time()` 预计算能量时间轴驱动口型，与声卡缓冲漂移，句尾嘴停 | 改为在播放回调取"当前发声片 RMS"存共享变量，泵线程读最新值发出，严格对齐实际播放 |
| Live2D 水印 | `getParameterCount` 不存在导致旧方案失效、水印常显 | 收集候选 core 对象，每帧双钩子强制 `Param191=1` |
| 跨电脑部署 | 绝对路径/写死 cuda/缺 venv 起不来 | 相对路径解析 + 设备自动探测 + `启动.bat` 一键自举 |
| ASR 离线稳定 | HuggingFace 国内被墙、模型下不全 | 本地 `models/` 内置权重优先；`download_model.py` 走 `hf-mirror.com` 镜像 + 断点续传 |
| 滚轮失效 | Canvas `yscrollincrement=0` 时 `units` 模式只滚 1px | 设 `yscrollincrement=1` + 步长放大到 `delta/3` + 延迟刷新 `scrollregion` |

---

## 五、性能与瓶颈

- 端到端延迟：ASR(CPU small ~3s) + LLM(~3s) + TTS(GPU/云端 ~数秒)。
- 语音识别本地 CPU 推理；TTS 走云端（需网络）；对话/视觉需各自 API Key。
- 已优化：口型与音频严格对齐、视觉失败时降级、记忆读写轻量。

---

## 六、扩展指南

1. **换对话模型**：`.env` 改 `OPENAI_BASE_URL`/`MODEL`，或在 GUI 运行时热替换。
2. **加 Live2D 形象**：把模型放 `assets/live2d/`，在 `live2d_models.py` 注册（标 `commercial=True`）。
3. **加工具**：在 `tools.py` 注册函数，并在 `assistant._route_action` 增加路由。
4. **调自主权限**：`config.py` 的 `AUTONOMY_WHITELIST` 增删条目，越界自动钳制。
5. **离线对话**：接入本地 OpenAI 兼容服务（Ollama / LM Studio）即可完全离线。

---

## 七、部署与运行

```bash
# 1. 安装 Python 3.10+（勾选 Add to PATH）
# 2. 双击 启动.bat（自动建 venv、装依赖、生成 .env、下载 ASR 模型）
# 3. 编辑 .env 填入 OPENAI_API_KEY / SEEDTTS_* / VISION_API_KEY（按需）
# 4. 再次双击 启动.bat 启动
```
- 语音识别模型已内置，离线可用；语音输出与对话/视觉需自备 Key。
- 个人数据（`data/`、`.env`）不入库，分发安全。

---

*技术栈：Python · Tkinter · Live2D(Cubism) · DeepSeek · 字节 Seed-TTS · faster-whisper · 智谱 GLM-4V · WebSocket*
