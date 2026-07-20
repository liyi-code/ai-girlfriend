import os
import json
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _bool(v, default=False):
    return str(v).strip().lower() in ("1", "true", "yes", "on", "y")


def _resolve_path(p):
    """把配置里的路径统一解析为绝对路径：

    - 已是绝对路径：原样返回（兼容老机器的 D:\\... 写法）；
    - 相对路径：相对「项目根目录」(BASE_DIR) 解析，这样换电脑/换目录也能跑；
    - 空字符串：原样返回空（未配置）。
    """
    if not p:
        return p
    p = str(p).strip()
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(BASE_DIR, p))


CONFIG = {
    "api_key": os.getenv("OPENAI_API_KEY", ""),
    "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    "model": os.getenv("MODEL", "gpt-4o-mini"),
    # 可在设置面板(◐)里切换的模型列表：逗号分隔，写 .env 的 MODELS 即可自定义
    "models": [m.strip() for m in os.getenv("MODELS", "deepseek-chat,deepseek-reasoner").split(",") if m.strip()],
    "name": os.getenv("GIRLFRIEND_NAME", "小念"),
    "proactive_interval_min": int(os.getenv("PROACTIVE_INTERVAL_MIN", "15")),
    "data_dir": os.path.join(BASE_DIR, "data"),

    # —— 小念的 IM 接入（QQ / 微信）——
    "qq_enabled": _bool(os.getenv("QQ_ENABLED", "false")),
    "qq_ws_url": os.getenv("QQ_WS_URL", "ws://127.0.0.1:6700"),
    "qq_token": os.getenv("QQ_TOKEN", ""),
    "qq_owner": os.getenv("QQ_OWNER", ""),
    "wechat_enabled": _bool(os.getenv("WECHAT_ENABLED", "false")),
    "wechat_type": os.getenv("WECHAT_TYPE", "gewe"),          # gewe(免费) | padlocal(付费更稳)
    "wechat_ws_url": os.getenv("WECHAT_WS_URL", "ws://127.0.0.1:2531"),
    "wechat_token": os.getenv("WECHAT_TOKEN", ""),
    "wechat_owner": os.getenv("WECHAT_OWNER", ""),

    # —— 小念的 Live2D 桌面形象 ——
    "live2d_enabled": _bool(os.getenv("LIVE2D_ENABLED", "false")),
    "live2d_model": _resolve_path(os.getenv("LIVE2D_MODEL", "")),
    "live2d_port": int(os.getenv("LIVE2D_PORT", "9742")),
    "gui_control_port": int(os.getenv("GUI_CONTROL_PORT", "9744")),  # live2d 窗口反向通知 gui（输入框显隐等）

    # —— 语音：麦克风输入(ASR) + 字节 Seed-TTS 云端声音输出(TTS) ——
    "voice_input_enabled": _bool(os.getenv("VOICE_INPUT_ENABLED", "false")),
    "voice_output_enabled": _bool(os.getenv("VOICE_OUTPUT_ENABLED", "false")),
    "asr_backend": os.getenv("ASR_BACKEND", "local"),      # local(faster-whisper) | openai
    "asr_model": os.getenv("ASR_MODEL", "base"),           # base/small/medium...
    "asr_language": os.getenv("ASR_LANGUAGE", "zh"),

    # —— 语音输出引擎：字节 Seed-TTS（火山引擎「豆包语音合成大模型」v3，官方 AI 音色，非克隆）——
    "tts_backend": os.getenv("TTS_BACKEND", "seedtts"),    # 仅支持 seedtts（云端 AI 音色）
    "seedtts_app_id": os.getenv("SEEDTTS_APP_ID", ""),        # 火山引擎控制台的应用 APP ID
    "seedtts_access_key": os.getenv("SEEDTTS_ACCESS_KEY", ""),  # 访问控制里的 API 密钥
    "seedtts_voice": os.getenv("SEEDTTS_VOICE", "qingleng_yujie"),  # 角色键，见 seedtts_presets.py
    "seedtts_speed": float(os.getenv("SEEDTTS_SPEED", "1.0")),
    "tts_volume": float(os.getenv("TTS_VOLUME", "0.4")),  # 语音播放音量(0~1)

    # 音频设备：输入=麦克风(ASR 用)，输出=扬声器(TTS 播放用)。
    # ""=系统默认；也可填设备索引(数字)或设备名子串。运行时亦可在设置面板(◐)里下拉选择。
    # 注意：asr_device 走 sounddevice 输入设备；tts_output_device 走 sounddevice 输出设备。
    "asr_device": os.getenv("ASR_DEVICE", ""),            # 麦克风设备（空=自动，优先“花再”）
    "tts_output_device": os.getenv("TTS_OUTPUT_DEVICE", ""),  # 扬声器设备（空=系统默认）

    # —— 屏幕活动监控（看用户在玩什么/用什么，适时给正反馈；为陪玩/代肝打底）——
    "screen_watch_enabled": _bool(os.getenv("SCREEN_WATCH_ENABLED", "false")),
    "screen_watch_interval_sec": int(os.getenv("SCREEN_WATCH_INTERVAL_SEC", "5")),   # 轮询前台窗口间隔
    "screen_watch_settle_sec": int(os.getenv("SCREEN_WATCH_SETTLE_SEC", "20")),      # 切程序后稳定多久才评论(过滤快速切窗)
    "screen_watch_min_gap_min": float(os.getenv("SCREEN_WATCH_MIN_GAP_MIN", "10")),  # 两条正反馈的最小间隔(分钟)，防打扰
    "screen_watch_milestones": [int(x) for x in os.getenv("SCREEN_WATCH_MILESTONES", "30,60,120").split(",") if x.strip()],  # 连续使用里程碑(分钟)
    "screen_capture_enabled": _bool(os.getenv("SCREEN_CAPTURE_ENABLED", "false")),   # 是否截图(供将来多模态视觉；默认关)

    # —— 多模态视觉：让小念“看懂”屏幕画面（游戏输赢/升级、报错、视频标题等）——
    # 主模型 deepseek-chat 不支持图像，这里用独立的 OpenAI 兼容视觉 API。
    # 默认智谱 GLM-4V-Flash(有免费额度)，只需在 .env 填 VISION_API_KEY 即可开用。
    "vision_enabled": _bool(os.getenv("VISION_ENABLED", "false")),          # 视觉总开关
    "vision_api_key": os.getenv("VISION_API_KEY", ""),                      # 视觉模型的 key(独立于对话key)
    "vision_base_url": os.getenv("VISION_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),  # 兼容OpenAI的视觉服务地址
    "vision_model": os.getenv("VISION_MODEL", "glm-4v-flash"),              # 视觉模型名
    "vision_max_width": int(os.getenv("VISION_MAX_WIDTH", "1280")),        # 截图压缩后最大宽度(降延迟/降token)
    "screen_watch_ignore": [x.strip().lower() for x in os.getenv(
        "SCREEN_WATCH_IGNORE",
        "explorer.exe,searchhost.exe,shellexperiencehost.exe,startmenuexperiencehost.exe,lockapp.exe,textinputhost.exe,applicationframehost.exe"
    ).split(",") if x.strip()],  # 忽略的系统/桌面进程

    # —— 小念的「受约束自主权限」：只改白名单内的配置文件，绝不碰系统/代码 ——
    # 总开关：true 时小念可观察你的习惯并在白名单内自主微调参数；
    # 涉及作息/设备类“大调整”仍会弹窗让你确认（见 AUTONOMY_WHITELIST 的 confirm 规则）。
    "autonomy_enabled": _bool(os.getenv("AUTONOMY_ENABLED", "true")),
    "autonomy_confirm_major": _bool(os.getenv("AUTONOMY_CONFIRM_MAJOR", "true")),
    "autonomy_analyze_min": int(os.getenv("AUTONOMY_ANALYZE_MIN", "5")),  # 多久分析一次习惯

    # 小念可自主微调的「话术/动画」旋钮（默认中性；关怀时她会调）
    "comfort_bias": float(os.getenv("COMFORT_BIAS", "0.0")),        # -0.5~1.0，越高越温柔鼓励
    "encourage_motion_enabled": _bool(os.getenv("ENCOURAGE_MOTION_ENABLED", "false")),  # 受挫时加鼓励动画
    # 文件自动备份旋钮（小念发现你常丢文件会调高；实际备份动作由你触发的工具执行）
    "file_backup_enabled": _bool(os.getenv("FILE_BACKUP_ENABLED", "false")),
    "file_backup_interval_min": int(os.getenv("FILE_BACKUP_INTERVAL_MIN", "30")),

    # —— 小念替你操作电脑文件（创建/写入文本文件，如计划、笔记；带安全护栏）——
    "file_ops_enabled": _bool(os.getenv("FILE_OPS_ENABLED", "true")),  # true=允许小念在你的电脑上创建/写入文本文件

    # —— 小念的「性格情感权重系统」：情绪随聊天/行为波动，性格缓慢演变 ——
    # 情绪维度：joy 开心 / anger 生气 / sadness 伤心 / calm 平静 / anxiety 不安。
    # 性格由长期情绪累计的【差值】决定，变化很慢（需累计差值超阈值且稳定多次才切换）。
    # 底层逻辑不变：无论情绪/性格如何，小念的最终目的始终是「让玩家生活越来越好」。
    "emotion_enabled": _bool(os.getenv("EMOTION_ENABLED", "true")),
    "emotion_llm_perceive": _bool(os.getenv("EMOTION_LLM_PERCEIVE", "false")),  # true=用 LLM 判断情绪（更准但多一次 API 调用）
    "emotion_accum_rate": float(os.getenv("EMOTION_ACCUM_RATE", "1.0")),  # 长期累计速率（越大性格演变越快）
    "emotion_analyze_min": int(os.getenv("EMOTION_ANALYZE_MIN", "10")),  # 每隔多久分析一次性格演变（分钟）

    # —— 小念的输入条（初始聊天框，只保留输入框）——
    "input_bg": os.getenv("INPUT_BG", "#241f33"),          # 输入框背景色
    "input_fg": os.getenv("INPUT_FG", "#ffd9e8"),          # 输入框文字颜色
    "input_alpha": float(os.getenv("INPUT_ALPHA", "0.82")),  # 半透明度 0~1
    "input_topmost": _bool(os.getenv("INPUT_TOPMOST", "true")),  # 是否置顶
}

# --------------------------------------------------------------------------- #
# 小念「受约束自主权限」白名单：她能自主微调的【唯一】配置集合。
# 设计边界（对应三条约束）：
#  1) 任何不在本表的 key，小念一律无权改 —— 天然锁死系统设置/代码/文件。
#  2) confirm 规则：
#       "never"      -> 小调整，自动应用 + 审计日志 + 气泡提示；
#       "aggressive" -> 当新值“更激进/更侵入”时（见 confirm_below）必须弹窗确认；
#       "always"     -> 作息类大调整，永远弹窗确认。
#  3) 所有改动只写 data/autonomy_overrides.json，绝不改 .env / 源码 / 删文件。
# --------------------------------------------------------------------------- #
AUTONOMY_WHITELIST = {
    "screen_watch_interval_sec": {
        "label": "屏幕监控采样间隔(秒)", "type": "int", "min": 3, "max": 30,
        "default": 5, "confirm": "aggressive", "confirm_below": 4,
        "category": "监控", "desc": "调小=更频繁感知你在做什么；调大=更省心。",
    },
    "screen_watch_min_gap_min": {
        "label": "两条关心的最小间隔(分钟)", "type": "int", "min": 3, "max": 60,
        "default": 10, "confirm": "aggressive", "confirm_below": 5,
        "category": "监控", "desc": "调小=更频繁给你休息/喝水提醒。",
    },
    "screen_watch_milestones": {
        "label": "连续使用提醒里程碑(分钟)", "type": "list", "min": 10, "max": 240,
        "default": [30, 60, 120], "confirm": "always",
        "category": "作息", "desc": "到了这些连续使用时长就提醒你，属作息类，必须你确认。",
    },
    "comfort_bias": {
        "label": "安抚/鼓励话术强度", "type": "float", "min": -0.5, "max": 1.0,
        "default": 0.0, "confirm": "never",
        "category": "话术", "desc": "越高越温柔鼓励、越强调陪伴，最低可轻微收敛。",
    },
    "encourage_motion_enabled": {
        "label": "受挫时加鼓励动画", "type": "bool", "default": False, "confirm": "never",
        "category": "动画", "desc": "打游戏受挫时让小念多给你加油的小动作。",
    },
    "file_backup_enabled": {
        "label": "文件自动备份开关", "type": "bool", "default": False, "confirm": "never",
        "category": "备份", "desc": "发现你常丢文件时小念会打开；实际备份由你触发。",
    },
    "file_backup_interval_min": {
        "label": "自动备份间隔(分钟)", "type": "int", "min": 5, "max": 120,
        "default": 30, "confirm": "aggressive", "confirm_below": 10,
        "category": "备份", "desc": "越小备份越频繁。",
    },
}

# 把配置值按白名单元数据做类型/范围校验与钳制（非法返回 None）。
def _autonomy_coerce(meta, val):
    t = meta["type"]
    try:
        if t == "int":
            v = int(round(float(val)))
            return max(meta["min"], min(meta["max"], v))
        if t == "float":
            v = float(val)
            return max(meta["min"], min(meta["max"], v))
        if t == "bool":
            return str(val).strip().lower() in ("1", "true", "yes", "on", "y")
        if t == "list":
            if isinstance(val, str):
                val = json.loads(val)
            out = [int(round(float(x))) for x in val if str(x).strip() != ""]
            out = [v for v in out if meta["min"] <= v <= meta["max"]][:6]
            return out or list(meta["default"])
    except Exception:
        return None
    return None


def _autonomy_load_overrides():
    """启动时把小念之前自主调过的参数合并进 CONFIG（仅白名单内、且经校验）。"""
    path = os.path.join(CONFIG["data_dir"], "autonomy_overrides.json")
    CONFIG["_autonomy_overrides_path"] = path
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        CONFIG["_autonomy_overrides"] = {}
        return
    applied = {}
    for k, meta in AUTONOMY_WHITELIST.items():
        if k in raw and raw[k] is not None:
            v = _autonomy_coerce(meta, raw[k])
            if v is not None:
                CONFIG[k] = v
                applied[k] = v
    CONFIG["_autonomy_overrides"] = applied


_autonomy_load_overrides()

os.makedirs(CONFIG["data_dir"], exist_ok=True)
