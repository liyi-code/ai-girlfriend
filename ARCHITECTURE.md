# 架构图 · 小念 AI 桌面女友

> 本图综合两个来源：**① 本仓库（GitHub 便携版 `ai桌面女友/ai-girlfriend`）的实际代码文件**；**② 与用户历史对话中记录的小念完整功能设计**（含主项目 `d:\AI训练\ai-girlfriend` 已实现、但本仓库尚未同步的「生活接入」等）。
> 技术栈：Python + tkinter（输入条/控制台） + WebView2 / Live2D（形象） + OpenAI 兼容 LLM + 语音（Seed-TTS 云端 / GPT-SoVITS 本地） + faster-whisper 本地识别 + 多模态视觉（GLM-4V）。
> 平台：Windows 桌面程序。

---

## 图例

- 🟦 实线箭头 `-->`：主调用 / 数据流（一次调用链上的硬依赖）。
- 🟪 点线箭头 `-.->`：认知注入（情绪/性格/屏幕/记忆/生活等"软信号"进入对话，并非每次都触发）。
- ⬜ 开放连线 `---`：同进程内的组件关联（如 Live2D 窗口 ↔ 渲染引擎）。
- 模块徽标：`✅仓库` = 已在本 GitHub 仓库 `src/` 中；`⚠主项目` = 仅主项目 `d:\AI训练\ai-girlfriend` 实现，本仓库**未含**（需同步才具备）。

---

## 0. 多副本差异（历史对话核心）

小念有多个本地副本，架构相同但能力/资源不同：

| 副本 | 路径 | 语音 TTS | Live2D | 生活接入(手机) | LLM |
|---|---|---|---|---|---|
| **便携版（GitHub）** | `ai桌面女友/ai-girlfriend` | 字节 Seed-TTS 云端 | hiyori_pro（可商用） | ❌ 未含 | DeepSeek / 兼容 |
| 主项目 | `d:\AI训练\ai-girlfriend` | Seed-TTS（已切） | Xiyu（非商用） | ✅ 已实现 | DeepSeek / 兼容 |
| 本地版 | `d:\AI训练\ai-girlfriend-本地版` | GPT-SoVITS 本地 | Xiyu | ❌ 未含 | 本地 Ollama |
| 备份 | `ai-girlfriend-备份-20260717` | GPT-SoVITS 本地 | Xiyu | ❌ 未含 | DeepSeek |

> 图里凡标 `⚠主项目` 的模块，本 GitHub 仓库当前没有。

---

## 1. 小念完整系统总览

```mermaid
flowchart TB
    subgraph USER[用户交互入口]
        IN["输入条（半透明悬浮框 · tkinter）"]
        L2DWIN["Live2D 形象窗口（WebView2）"]
        CON["整合控制台 Ctrl+Alt+G"]
        SET["设置面板 ◐ / 心情面板 Ctrl+Alt+E"]
        PHONE["手机 App ⚠主项目"]
    end

    subgraph APP[桌面程序 · Windows · Python]
        direction TB
        subgraph ENTRY[入口与编排 ✅仓库]
            MAIN["main.py"]
            GUI["gui.py  输入条·控制台·主动关心线程·socket 调度"]
            CFG["config.py  配置·路径·设备探测·自主白名单"]
        end
        subgraph COG[认知与感知层]
            ASST["assistant.py  LLM 对话·工具编排·系统提示拼装 ✅仓库"]
            EMOT["emotion.py  情绪5维 + 性格派生 ✅仓库"]
            AUTO["autonomy.py  受约束自主权限引擎 ✅仓库"]
            SW["screen_watch.py  屏幕感知（窗口/进程名）✅仓库"]
            VIS["vision.py  多模态视觉（GLM-4V）✅仓库"]
            MEM["memory.py  记忆（本地 JSON）✅仓库"]
            LIFE["life_context.py  生活情境引擎 ⚠主项目"]
        end
        subgraph IO[输入/输出层 ✅仓库]
            VOICE["voice.py  TTS(Seed-TTS云端) · ASR(whisper)"]
            L2D["live2d_app.py  Live2D 渲染·嘴型·动作"]
            TOOLS["tools.py  开软件·搜文件·跑命令·写笔记·看屏"]
            LAUNCH["launcher.py  应用启动器"]
            LS["life_server.py  HTTP :9755 ⚠主项目"]
        end
        subgraph OPS[运维 ✅仓库]
            UPD["updater.py  git-free 自动更新"]
        end
    end

    subgraph EXT[外部服务与资源]
        LLM[("LLM API  DeepSeek / 本地 Ollama")]
        TTS[("TTS：Seed-TTS 云端 / GPT-SoVITS 本地")]
        WH[("faster-whisper 本地")]
        VAPI[("视觉 API  GLM-4V")]
        GH[("GitHub 仓库")]
        MDL[("Live2D 模型  hiyori_pro / Xiyu")]
    end

    IN --> GUI
    CON --> GUI
    SET --> GUI
    MAIN --> GUI
    GUI --> ASST
    GUI --> L2D
    GUI --> UPD
    PHONE -->|HTTP POST| LS
    LS --> LIFE
    ASST --> LLM
    ASST --> TOOLS
    ASST --> MEM
    TOOLS --> LAUNCH
    TOOLS --> VIS
    VIS --> VAPI
    ASST --> VOICE
    VOICE --> TTS
    VOICE --> WH
    ASST -. "性格/情绪/屏幕/记忆/生活 注入" .-> EMOT
    ASST -.-> AUTO
    ASST -.-> SW
    ASST -.-> VIS
    ASST -.-> LIFE
    L2D --> MDL
    UPD -. "更新检查/应用" .-> GH
    L2DWIN --- L2D
```

---

## 2. 一次对话与响应的数据流

```mermaid
flowchart LR
    A["用户输入<br/>文字 / 语音"] --> B{"语音输入?"}
    B -->|是| C["voice.ASR<br/>faster-whisper 转写"]
    B -->|否| D["文本"]
    C --> D
    D --> E["assistant.chat()"]
    E --> F["拼装 system_prompt<br/>性格 + 情绪 + 屏幕 + 记忆 + 生活情境 + 自主"]
    F --> G["调用 LLM（OpenAI 兼容）"]
    G --> H{"需要调用工具?"}
    H -->|看屏幕| I["vision.look_at_screen"]
    H -->|开软件/跑命令| J["tools → launcher"]
    H -->|写笔记| K["tools.create_text_file"]
    I --> G
    J --> G
    K --> G
    G --> L["回复文本"]
    L --> M["gui 气泡 + 控制台显示"]
    L --> N["voice.TTS<br/>合成 wav（Seed-TTS 云端）"]
    N --> O["扬声器播放 + 实时 RMS 口型"]
    O --> P["live2d_app  setMouth / 动作"]
    L --> Q["memory 存入对话历史"]
```

---

## 3. 生活接入链路（手机 → 主动关心）⚠主项目独有

> 仅主项目 `d:\AI训练\ai-girlfriend` 实现，本 GitHub 仓库未含。

```mermaid
sequenceDiagram
    participant P as 手机 App
    participant LS as life_server :9755
    participant LC as life_context
    participant A as assistant
    participant G as gui（主动关心）
    participant MEM as memory
    P->>LS: POST /life/signal（body 带 token）
    LS->>LC: feed(signals)
    LC->>LC: 状态融合 → 派生事件（到家/吃饭/低落…）
    LC-->>A: on_life_event 注入情境
    A->>G: 主动发一条贴合情境的关心
    G->>P: 推送 / 弹窗
    P->>LS: POST /life/memory
    LS->>MEM: 写入记忆（事实/画像）
```

控制台「生活感知」面板有模拟按钮（走 `simulate()` 强制触发，绕过冷却，便于测试）。

---

## 4. 认知引擎如何注入对话（情绪/性格/自主/屏幕/生活）

```mermaid
flowchart TB
    SIG["用户行为信号<br/>聊天内容 / 屏幕活动 / 使用习惯 / 手机生活信号"]
    SIG --> EMOT
    SIG --> AUTO
    SIG --> SW
    SIG --> LIFE
    EMOT -->|"性格（长期演变，驱动自主与话术）"| ASST
    EMOT -->|"情绪（短期波动）"| L2DACT["Live2D 表情/动作/语音声调"]
    EMOT -->|"情绪（短期波动）"| ASST
    AUTO -->|"习惯/健康分析（不读情绪，健康护栏）"| ASST
    SW -->|"程序级 + 像素级画面"| ASST
    LIFE -->|"下班/吃饭/心情等情境"| ASST
    ASST --> PC["主动关心 / 回复"]
    PC --> M["gui 主动发消息"]
    M --> L2DWIN["Live2D + 语音反馈"]
```

设计要点：**情绪**只影响聊天语气与动作表情；**性格**由情绪长期累计派生，额外驱动自主行为与话术；**自主（autonomy）的 analyze 只依据习惯/健康信号，不读情绪**，避免被情绪带偏。

---

## 5. 模块依赖关系（src，标注归属）

```mermaid
graph LR
    MAIN["main.py ✅仓库"] --> GUI["gui.py ✅仓库"]
    GUI --> ASST["assistant.py ✅仓库"]
    GUI --> VOICE["voice.py ✅仓库"]
    GUI --> L2D["live2d_app.py ✅仓库"]
    GUI --> UPD["updater.py ✅仓库"]
    GUI --> LS["life_server.py ⚠主项目"]
    ASST --> MEM["memory.py ✅仓库"]
    ASST --> TOOLS["tools.py ✅仓库"]
    ASST --> EMOT["emotion.py ✅仓库"]
    ASST --> AUTO["autonomy.py ✅仓库"]
    ASST --> SW["screen_watch.py ✅仓库"]
    ASST --> VIS["vision.py ✅仓库"]
    ASST --> LIFE["life_context.py ⚠主项目"]
    ASST --> CFG["config.py ✅仓库"]
    TOOLS --> LAUNCH["launcher.py ✅仓库"]
    TOOLS --> VIS
    GUI --> CFG
    GUI --> MEM
    L2D --> CFG
    UPD --> CFG
    AUTO --> CFG
    AUTO --> MEM
    EMOT --> CFG
    VIS --> CFG
    VOICE --> CFG
    SW --> CFG
```

> 本 GitHub 仓库 `src/` 实际文件（共 14 个）：`assistant / autonomy / config / emotion / gui / launcher / live2d_app / main / memory / screen_watch / tools / updater / vision / voice`。其中 `life_context / life_server` 不在仓库内（见第 0 节）。

根目录辅助模块：`seedtts_presets.py`（5 种云端 AI 音色预设）、`live2d_models.py`（Live2D 模型注册）、`download_model.py`（拉取 ASR 模型）、`启动.bat`（一键自举 venv/依赖）。

---

## 6. 启动流程

```mermaid
flowchart LR
    BAT["启动.bat"] --> VENV["建/复用 venv + 装 requirements.txt"]
    VENV --> DL["download_model.py 拉取 ASR 模型（可选）"]
    DL --> RUN["python -m src.main"]
    RUN --> TK["tk.Tk() 根窗口"]
    TK --> APP["App(root) 初始化各引擎"]
    APP --> WIN["启动 Live2D 窗口（WebView2）"]
    APP --> TH["启动主动关心线程"]
    APP --> LIFEUP["起 life_server :9755 ⚠主项目"]
    APP --> UPDT["8 秒后后台检查更新"]
    APP --> LOOP["root.mainloop() 事件循环"]
```

---

## 7. 外部依赖与数据文件

### 外部服务
| 能力 | 服务 | 说明 |
|---|---|---|
| 对话 LLM | DeepSeek / 本地 Ollama | OpenAI 兼容接口 |
| 语音输出 TTS | 字节 Seed-TTS 云端（火山引擎） / GPT-SoVITS 本地 | 便携版=Seed-TTS 云端 AI 音色（非克隆） |
| 语音输入 ASR | faster-whisper（本地） | 离线识别，模型在 `models/faster-whisper-*` |
| 多模态视觉 | 智谱 GLM-4V-Flash（可换本地 llama3.2-vision） | 看懂屏幕画面 |
| 形象 | Live2D：hiyori_pro（便携版，可商用）/ Xiyu（主项目，非商用） | 位于 `assets/live2d/` |
| 自动更新源 | GitHub 仓库 | `updater.py` 走 git tree 比对，git-free |
| 生活接入（主项目） | 手机 App → `life_server` :9755 | 需 Tailscale/同网，暂未做手机端 |

### 本地数据 / 配置
| 文件 | 作用 |
|---|---|
| `data/memory.json` | 对话历史 / 事实 / 用户画像 |
| `data/autonomy_overrides.json` | 小念自主微调过的参数记录 |
| `data/input_style.json` | 输入条位置/颜色/透明度 |
| `data/screen_watch/` | 屏幕截图（视觉用） |
| `.update_manifest.json` / `.update_backup/` | 自动更新状态与回滚备份 |
| `.env` / `.env.example` | 运行配置（密钥、开关、模型） |
| `seedtts_presets.py` / `live2d_models.py` | 音色预设 / 形象注册 |
