import sys
import os
import json
import time
import socket
import threading
import subprocess
import tkinter as tk
from tkinter import scrolledtext, messagebox, colorchooser, filedialog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CONFIG, BASE_DIR
from assistant import Assistant
import tools
from launcher import launcher
from voice import VoiceInput, TTS


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"{CONFIG['name']} · 你的 AI 女友")

        # 只保留输入框：无边框、可拖动、半透明悬浮条。其余反馈交给模型气泡/语音。
        root.geometry("470x54")
        root.overrideredirect(True)                       # 去标题栏
        root.attributes("-topmost", CONFIG["input_topmost"])
        try:
            root.attributes("-alpha", float(CONFIG["input_alpha"]))  # 半透明
        except Exception:
            pass

        # 样式（运行时可调，持久化到 data/input_style.json，覆盖 .env 默认值）
        self.style_path = os.path.join(CONFIG["data_dir"], "input_style.json")
        self.style = self.load_style()

        # 主题化悬浮条：accent 细边框 + 内边距，模拟圆角卡片观感
        self.bar = tk.Frame(root, padx=6, pady=6,
                            highlightbackground=self.THEME["accent"], highlightthickness=1)
        self.bar.pack(fill=tk.BOTH, expand=True)

        # 左侧拖动握把（≡），按住可移动整条
        self.grip = tk.Label(self.bar, text="≡", font=("Microsoft YaHei", 12),
                             cursor="fleur", width=2)
        self.grip.pack(side=tk.LEFT, padx=(0, 4))

        # 设置按钮：打开输入条设置面板
        self.settings_btn = self._bar_btn(self.bar, "◐", self.toggle_settings)
        self.settings_btn.pack(side=tk.LEFT, padx=(0, 4))

        # 麦克风按钮：点击切换录音
        self.mic_btn = self._bar_btn(self.bar, "🎤", self._mic_toggle)
        self.mic_btn.pack(side=tk.LEFT, padx=(0, 4))

        # 历史记录按钮：查看与小念的过往聊天记录
        self.history_btn = self._bar_btn(self.bar, "📜", self.view_history)
        self.history_btn.pack(side=tk.LEFT, padx=(0, 4))

        # 语音状态提示（可见，避免报错被藏进隐藏聊天框看不到）
        self.voice_status = tk.Label(self.bar, text="", font=("Microsoft YaHei", 9),
                                     fg=self.THEME["accent2"], bg=CONFIG["input_bg"])
        self.voice_status.pack(side=tk.LEFT, padx=(0, 4))

        # 输入框：颜色可自定义 + 占位提示
        self.entry = tk.Entry(self.bar, font=("Microsoft YaHei", 11),
                              relief=tk.FLAT, highlightthickness=1,
                              highlightbackground=self.THEME["line"],
                              bd=0, bg=CONFIG["input_bg"], fg=CONFIG["input_fg"],
                              insertbackground=self.THEME["accent"])
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        self._show_placeholder()
        self.entry.bind("<Return>", lambda e: self.send())
        self.entry.bind("<FocusIn>", lambda e: self._clear_placeholder())
        self.entry.bind("<FocusOut>", lambda e: self._show_placeholder())
        self.entry.focus_set()

        # 发送 / 关闭按钮
        self.send_btn = tk.Button(self.bar, text="发送", command=self.send,
                                  bg=self.THEME["accent"], fg="#ffffff",
                                  activebackground=self.THEME["accent2"],
                                  activeforeground="#ffffff",
                                  relief=tk.FLAT, font=("Microsoft YaHei", 10, "bold"),
                                  padx=12, cursor="hand2")
        self.send_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self.close_btn = self._bar_btn(self.bar, "×", self._on_close, size=12)
        self.close_btn.pack(side=tk.RIGHT, padx=(2, 0))

        self.settings_win = None
        self.console_win = None
        self.apply_style()   # 应用已保存 / 默认样式

        # 拖动：握把或条上空白区可拖动；点输入框则正常打字
        def on_press(e):
            if e.widget is not self.bar and e.widget is not self.grip:
                return
            root._dx, root._dy = e.x, e.y
            root._drag = True
        def on_drag(e):
            if not getattr(root, "_drag", False):
                return
            x = root.winfo_x() + (e.x - root._dx)
            y = root.winfo_y() + (e.y - root._dy)
            root.geometry(f"+{x}+{y}")
        def on_release(e):
            if getattr(root, "_drag", False):
                root._drag = False
                self._save_pos()
        for w in (self.bar, self.grip):
            w.bind("<Button-1>", on_press)
            w.bind("<B1-Motion>", on_drag)
            w.bind("<ButtonRelease-1>", on_release)

        # 聊天记录区：按需求不显示，仅保留内部接口（append 仍被其它逻辑调用），
        # 小念的回复改由模型动作 + 气泡框 + 后续语音反馈。
        self.chat = scrolledtext.ScrolledText(root)
        self.chat.config(state=tk.DISABLED)

        self.assistant = None
        self.live2d_proc = None

        # 受约束自主权限引擎：让小念在白名单内围绕“让生活更好”自调参
        # （只写 data/autonomy_overrides.json，绝不动系统/代码/文件）
        self.autonomy = None
        try:
            from autonomy import Autonomy
            self.autonomy = Autonomy(self)
        except Exception as e:
            self.append("系统", f"自主权限未启动：{e}")

        # 语音：输入(ASR) / 输出(TTS)，配置驱动、可降级
        self.voice = VoiceInput(
            enabled=CONFIG.get("voice_input_enabled", False),
            backend=CONFIG.get("asr_backend", "local"),
            model=CONFIG.get("asr_model", "base"),
            language=CONFIG.get("asr_language", "zh"),
            device=CONFIG.get("asr_device", ""),
        )
        self.tts = TTS(
            enabled=CONFIG.get("voice_output_enabled", False),
            backend=CONFIG.get("tts_backend", "seedtts"),
            seedtts_app_id=CONFIG.get("seedtts_app_id", ""),
            seedtts_access_key=CONFIG.get("seedtts_access_key", ""),
            seedtts_voice=CONFIG.get("seedtts_voice", "qingleng_yujie"),
            seedtts_speed=CONFIG.get("seedtts_speed", 1.0),
            volume=self.style.get("volume", CONFIG["tts_volume"]),
            output_device=CONFIG.get("tts_output_device", ""),
        )
        # 应用已保存的音频设备选择（运行时生效，无需重启）
        self.voice.device = self.style.get("input_device", "")
        self.tts.output_device = self.style.get("output_device", "")

        try:
            self.assistant = Assistant(autonomy=self.autonomy)
            self._apply_model_state()   # 应用已保存的模型选择
            self._init_reply_queue()   # 回复队列 + 主动关心计时（用户连续输入串行输出）
            self.start_proactive()     # 并行条件循环：空闲关心 / 软件搭话
            self.start_screen_watch()   # 屏幕活动监控 → 适时给正反馈
            self.start_control_server()  # 接收 live2d 窗口反向指令（输入框显隐）
            self.start_hotkeys()    # 全局快捷键：Ctrl+Alt+V 语音输入 / Ctrl+Alt+G 控制台
            if self.autonomy is not None:
                self.autonomy.start()   # 启动习惯分析线程（受 autonomy_enabled 控制）
        except RuntimeError as e:
            self.append("系统", str(e))

        # 让“打开软件”等动作在主线程（UI 线程）执行
        launcher.bind_main_thread(lambda fn: self.root.after(0, fn))

        # 启动 IM 接入（QQ/微信）
        if self.assistant is not None:
            try:
                from bot import Bot
                self.bot = Bot(self.assistant).setup()
                self.bot.start()
            except Exception as e:
                self.append("系统", f"IM 接入未启动（不影响本地聊天）：{e}")

        # 启动小念的 Live2D 桌面形象窗口（独立进程，透明桌宠）
        if CONFIG.get("live2d_enabled"):
            self._start_live2d()
            # 启动后让小念用气泡主动打个招呼（等形象窗口 TCP 就绪）
            root.after(2600, lambda: self.live2d_say(
                f"在呢～我是{CONFIG['name']}，你的专属 AI 女友。想聊什么、"
                f"要我帮你开软件查东西，都可以跟我说哦 💕"))

        # 语音输出：Seed-TTS 是云端服务，无需本地拉起，直接可用（前提是已填密钥）。

        # 关闭主窗口时一并结束形象子进程，避免白框残留
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 初始定位：优先用上次记住的位置，否则放屏幕底部居中（仅定位，不改尺寸）
        def _place():
            try:
                p = self.style.get("pos")
                if isinstance(p, (list, tuple)) and len(p) == 2:
                    x, y = int(p[0]), int(p[1])
                else:
                    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
                    x, y = max(0, sw // 2 - 235), max(0, sh - 120)
                root.geometry(f"+{x}+{y}")
            except Exception:
                pass
        root.after(0, _place)

    def append(self, who, text):
        self.chat.config(state=tk.NORMAL)
        self.chat.insert(tk.END, f"{who}：{text}\n\n")
        self.chat.config(state=tk.DISABLED)
        self.chat.see(tk.END)

    # ---------- 聊天记录查看 ----------
    def view_history(self):
        """打开一个窗口，查看小念和你的过往聊天记录。"""
        if self.assistant is None:
            return
        win = tk.Toplevel(self.root)
        win.title(f"{CONFIG['name']} · 聊天记录")
        win.geometry("580x540")
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

        frm = tk.Frame(win)
        frm.pack(fill=tk.X, padx=6, pady=4)
        tk.Label(frm, text="过往聊天记录（最新在底部）", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        tk.Button(frm, text="复制全部", command=lambda: _copy()).pack(side=tk.RIGHT, padx=4)
        tk.Button(frm, text="刷新", command=lambda: _load()).pack(side=tk.RIGHT, padx=4)

        txt = scrolledtext.ScrolledText(win, font=("Microsoft YaHei", 10), wrap=tk.WORD)
        txt.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        def _load():
            txt.config(state=tk.NORMAL)
            txt.delete("1.0", tk.END)
            hist = self.assistant.memory.data.get("history", [])
            name = CONFIG["name"]
            if not hist:
                txt.insert(tk.END, "还没有聊天记录哦～先跟我聊聊吧💕")
            else:
                for m in hist:
                    role = m.get("role", "")
                    who = "你" if role == "user" else name
                    t = m.get("time", "")
                    content = m.get("content", "")
                    txt.insert(tk.END, f"【{who}】 {t}\n{content}\n\n")
            txt.config(state=tk.DISABLED)
            txt.see(tk.END)

        def _copy():
            rows = self.assistant.memory.data.get("history", [])
            all_text = "\n".join(
                f"[{m.get('role', '')}] {m.get('time', '')}\n{m.get('content', '')}"
                for m in rows
            )
            try:
                win.clipboard_clear()
                win.clipboard_append(all_text)
                self.show_voice_status("已复制全部聊天记录", 2000)
            except Exception:
                pass

        _load()

    # ---------- 输入条样式：运行时可调 + 持久化 ----------
    def load_style(self):
        default = {
            "alpha": float(CONFIG["input_alpha"]),
            "bg": CONFIG["input_bg"],
            "fg": CONFIG["input_fg"],
            "volume": float(CONFIG["tts_volume"]),
            "input_device": "",   # 麦克风设备：""=系统默认(优先花再)；或索引/名子串
            "output_device": "",  # 扬声器设备：""=系统默认；或索引/名子串
        }
        try:
            with open(self.style_path, encoding="utf-8") as f:
                saved = json.load(f)
            for k in default:
                if k in saved and saved[k] is not None:
                    default[k] = saved[k]
        except Exception:
            pass
        return default

    def save_style(self):
        try:
            with open(self.style_path, "w", encoding="utf-8") as f:
                json.dump(self.style, f, ensure_ascii=False)
        except Exception:
            pass

    # ---------- 音频设备枚举（麦克风 / 扬声器）----------
    @staticmethod
    def list_audio_devices():
        """枚举声卡设备，返回 (inputs, outputs)，各为 [(idx, name), ...]。

        用 sounddevice 的 query_devices；若 sounddevice 不可用则都返回空列表
        （界面只会显示「系统默认」一项，不影响其它功能）。
        """
        ins, outs = [], []
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                name = d.get("name", f"设备{i}")
                if d.get("max_input_channels", 0) > 0:
                    ins.append((i, name))
                if d.get("max_output_channels", 0) > 0:
                    outs.append((i, name))
        except Exception:
            pass
        return ins, outs

    @staticmethod
    def _device_label(idx, devs):
        """根据已存的设备值(索引/名子串/空)反查下拉框应显示的 label。"""
        if not idx:
            return "（系统默认）"
        s = str(idx)
        for i, n in devs:
            if str(i) == s:
                return f"{n} (#{i})"
        # 存的是名子串的情况：按子串模糊匹配
        for i, n in devs:
            if s and s.lower() in n.lower():
                return f"{n} (#{i})"
        return "（系统默认）"

    @staticmethod
    def _device_value(label):
        """把下拉框 label 解析回设备值：默认返回 ''，否则返回索引字符串。"""
        if not label or label == "（系统默认）":
            return ""
        h = label.rfind("#")
        if h == -1:
            return label.strip()
        return label[h + 1:].rstrip(")")

    # ---------- 模型 / 音色 切换（运行时生效 + 持久化）----------
    def _models_path(self):
        return os.path.join(CONFIG["data_dir"], "models.json")

    def _load_model_state(self):
        default = {"current": CONFIG["model"], "models": list(CONFIG["models"])}
        try:
            with open(self._models_path(), encoding="utf-8") as f:
                s = json.load(f)
            if s.get("current"):
                default["current"] = s["current"]
            if isinstance(s.get("models"), list) and s["models"]:
                default["models"] = s["models"]
        except Exception:
            pass
        return default

    def _save_model_state(self, current, models):
        try:
            with open(self._models_path(), "w", encoding="utf-8") as f:
                json.dump({"current": current, "models": models}, f, ensure_ascii=False)
        except Exception:
            pass

    def _apply_model_state(self):
        if self.assistant is None:
            return
        self.assistant.model = self._load_model_state()["current"]

    def _on_model_change(self, value, models):
        if self.assistant is not None:
            self.assistant.model = value
        self._save_model_state(value, models)
        self.show_voice_status(f"🤖 已切换模型：{value}", 3000)

    # ---------- API 设置（运行时更换服务商 / 密钥 / 模型，无需重启）----------
    def _write_env_value(self, key, value):
        """把某个配置写回 .env（保留其它行与注释），下次启动仍生效。"""
        path = os.path.join(BASE_DIR, ".env")
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            lines = []
        out, replaced = [], False
        for ln in lines:
            if ln.startswith(key + "=") or ln.startswith(key + " ="):
                out.append(f"{key}={value}\n")
                replaced = True
            else:
                out.append(ln)
        if not replaced:
            out.append(f"{key}={value}\n")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(out)
            return True
        except Exception:
            return False

    def _build_api_section(self, parent):
        """在任意面板里插入「API 设置」分区：Key + Base URL + 模型 + 测试/保存。"""
        self._hdr(parent, "API 设置", "更换服务商 / 密钥 / 模型")
        self._flabel(parent, "API Key")
        key_var = tk.StringVar(value=CONFIG.get("api_key", ""))
        key_entry = self._entry(parent, textvariable=key_var, show="*")
        show_var = tk.BooleanVar(value=False)
        def _toggle_show():
            key_entry.config(show="" if show_var.get() else "*")
        self._check(parent, "显示密钥", variable=show_var, command=_toggle_show)
        self._flabel(parent, "Base URL（接口地址，如 https://api.deepseek.com/v1）")
        url_var = tk.StringVar(value=CONFIG.get("base_url", ""))
        self._entry(parent, textvariable=url_var)
        self._flabel(parent, "模型名（如 deepseek-chat / gpt-4o-mini / 本地模型名）")
        model_var = tk.StringVar(value=CONFIG.get("model", ""))
        self._entry(parent, textvariable=model_var)
        row = tk.Frame(parent, bg=self.THEME["panel"])
        row.pack(padx=14, pady=(10, 4))
        self._btn(row, "测试连接",
                  lambda: self._on_api_test(key_var, url_var, model_var), width=12
                  ).pack(side=tk.LEFT, padx=4)
        self._btn(row, "保存并应用",
                  lambda: self._on_api_save(key_var, url_var, model_var),
                  hot=True, width=12).pack(side=tk.LEFT, padx=4)

    def _on_api_test(self, key_var, url_var, model_var):
        key = key_var.get().strip()
        url = url_var.get().strip()
        model = model_var.get().strip() or CONFIG.get("model", "")
        if not key or not url:
            self.show_voice_status("请先填写 API Key 和 Base URL", 4000)
            return
        self.show_voice_status("正在测试连接…", 2000)

        def _run():
            try:
                from openai import OpenAI
                c = OpenAI(api_key=key, base_url=url)
                r = c.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=8,
                )
                txt = (r.choices[0].message.content or "").strip()
                self.root.after(0, lambda: self.show_voice_status(
                    f"✅ 连接成功：{(txt[:24] or '空回复')!r}", 5000))
            except Exception as e:
                msg = str(e)
                if len(msg) > 220:
                    msg = msg[:220] + "…"
                self.root.after(0, lambda: self.show_voice_status(
                    f"❌ 连接失败：{msg}", 9000))
        threading.Thread(target=_run, daemon=True).start()

    def _on_api_save(self, key_var, url_var, model_var):
        key = key_var.get().strip()
        url = url_var.get().strip()
        model = model_var.get().strip() or CONFIG.get("model", "")
        if not key or not url:
            self.show_voice_status("⚠ API Key 和 Base URL 不能为空", 4000)
            return
        # 热替换客户端（无需重启）
        if self.assistant is not None:
            try:
                self.assistant.set_api(api_key=key, base_url=url, model=model)
            except Exception as e:
                self.show_voice_status(f"⚠ 应用失败：{e}", 6000)
                return
        # 持久化到 .env，下次启动仍生效
        self._write_env_value("OPENAI_API_KEY", key)
        self._write_env_value("OPENAI_BASE_URL", url)
        self._write_env_value("MODEL", model)
        # 同步模型下拉（models.json），让“对话模型”下拉也能反映新模型
        mst = self._load_model_state()
        models = list(mst["models"])
        if model and model not in models:
            models.append(model)
        self._save_model_state(model, models)
        self.show_voice_status(f"✅ 已更换 API：{model} @ {url}", 5000)

    # ---------- 视觉（看屏）API 设置：GLM-4V-Flash 等，可独立更换 ----------
    def _build_vision_api_section(self, parent):
        """在任意面板里插入「视觉 API 设置」分区：启用 + Key + Base URL + 模型 + 测试/保存。"""
        self._hdr(parent, "视觉 API", "看懂屏幕 · 独立密钥")
        en_var = tk.BooleanVar(value=bool(CONFIG.get("vision_enabled")))
        self._check(parent, "启用视觉（让小念看懂屏幕）", variable=en_var,
                    command=lambda: self._on_vision_enable(en_var))
        self._flabel(parent, "视觉 API Key（如智谱 GLM-4V-Flash 的 key）")
        vkey_var = tk.StringVar(value=CONFIG.get("vision_api_key", ""))
        vkey_entry = self._entry(parent, textvariable=vkey_var, show="*")
        vshow_var = tk.BooleanVar(value=False)
        self._check(parent, "显示密钥",
                    variable=vshow_var,
                    command=lambda: vkey_entry.config(show="" if vshow_var.get() else "*"))
        self._flabel(parent, "视觉 Base URL（如 https://open.bigmodel.cn/api/paas/v4）")
        vurl_var = tk.StringVar(value=CONFIG.get("vision_base_url", "https://open.bigmodel.cn/api/paas/v4"))
        self._entry(parent, textvariable=vurl_var)
        self._flabel(parent, "视觉模型名（如 glm-4v-flash / glm-4v / gpt-4o）")
        vmodel_var = tk.StringVar(value=CONFIG.get("vision_model", "glm-4v-flash"))
        self._entry(parent, textvariable=vmodel_var)
        row = tk.Frame(parent, bg=self.THEME["panel"])
        row.pack(padx=14, pady=(10, 4))
        self._btn(row, "测试连接",
                  lambda: self._on_vision_api_test(vkey_var, vurl_var, vmodel_var), width=12
                  ).pack(side=tk.LEFT, padx=4)
        self._btn(row, "保存并应用",
                  lambda: self._on_vision_api_save(vkey_var, vurl_var, vmodel_var),
                  hot=True, width=12).pack(side=tk.LEFT, padx=4)

    def _on_vision_enable(self, en_var):
        val = "true" if en_var.get() else "false"
        self._write_env_value("VISION_ENABLED", val)
        CONFIG["vision_enabled"] = en_var.get()
        self.show_voice_status(f"视觉已{'启用' if en_var.get() else '关闭'}（下次看懂屏幕时生效）", 3500)

    def _on_vision_api_test(self, key_var, url_var, model_var):
        key = key_var.get().strip()
        url = url_var.get().strip()
        model = model_var.get().strip() or CONFIG.get("vision_model", "glm-4v-flash")
        if not key or not url:
            self.show_voice_status("请先填写视觉 API Key 和 Base URL", 4000)
            return
        self.show_voice_status("正在测试视觉连接…", 2000)
        # 1x1 透明 PNG，用于让视觉模型真正走图像接口验证连通性
        PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
               "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

        def _run():
            try:
                from openai import OpenAI
                c = OpenAI(api_key=key, base_url=url)
                r = c.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": "ping"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG}"}},
                    ]}],
                    max_tokens=8,
                )
                txt = (r.choices[0].message.content or "").strip()
                self.root.after(0, lambda: self.show_voice_status(
                    f"✅ 视觉连接成功：{(txt[:24] or '空回复')!r}", 5000))
            except Exception as e:
                msg = str(e)
                if len(msg) > 220:
                    msg = msg[:220] + "…"
                self.root.after(0, lambda: self.show_voice_status(
                    f"❌ 视觉连接失败：{msg}", 9000))
        threading.Thread(target=_run, daemon=True).start()

    def _on_vision_api_save(self, key_var, url_var, model_var):
        key = key_var.get().strip()
        url = url_var.get().strip()
        model = model_var.get().strip() or CONFIG.get("vision_model", "glm-4v-flash")
        if not key or not url:
            self.show_voice_status("⚠ 视觉 API Key 和 Base URL 不能为空", 4000)
            return
        try:
            import vision
            vision.set_vision_api(api_key=key, base_url=url, model=model)
        except Exception as e:
            self.show_voice_status(f"⚠ 视觉应用失败：{e}", 6000)
            return
        self._write_env_value("VISION_API_KEY", key)
        self._write_env_value("VISION_BASE_URL", url)
        self._write_env_value("VISION_MODEL", model)
        self.show_voice_status(f"✅ 已更换视觉 API：{model} @ {url}", 5000)

    # ---------- Live2D 形象切换（运行时生效 + 持久化到 .env LIVE2D_MODEL）----------
    def _discover_live2d_models(self):
        """扫描可用 Live2D 模型（assets/live2d 下所有 *.model3.json）。返回 [(显示名, 相对项目根路径)]。"""
        found = []
        adir = os.path.join(BASE_DIR, "assets", "live2d")
        if os.path.isdir(adir):
            for dp, _, files in os.walk(adir):
                for f in files:
                    if f.lower().endswith(".model3.json"):
                        ap = os.path.abspath(os.path.join(dp, f))
                        rel = os.path.relpath(ap, BASE_DIR).replace(os.sep, "/")
                        name = f[: -len(".model3.json")]
                        found.append((name, rel))
        seen, uniq = set(), []
        for name, rel in found:
            if rel not in seen:
                seen.add(rel)
                uniq.append((name, rel))
        return uniq

    def _switch_live2d_model(self, rel, label=None):
        """切换 Live2D 形象（写回 .env + 通知前端重新加载）。"""
        if not rel:
            return
        # 记忆上次选择（即使形象未运行也能记住）
        try:
            with open(os.path.join(CONFIG["data_dir"], "live2d_model.json"),
                      "w", encoding="utf-8") as f:
                json.dump({"current": rel}, f, ensure_ascii=False)
        except Exception:
            pass
        if not CONFIG.get("live2d_enabled"):
            return
        try:
            with socket.create_connection(("127.0.0.1", CONFIG["live2d_port"]), timeout=1) as s:
                s.sendall(json.dumps({"switch_live2d_model": rel}).encode("utf-8"))
        except Exception:
            pass
        if label:
            self.show_voice_status(f"🧸 已切换形象：{label}", 3000)

    def _on_live2d_model_change(self, value, models):
        rel = models.get(value)
        if not rel:
            return
        self._switch_live2d_model(rel, label=value)

    def _open_model_manager(self):
        """形象管理：列出所有已发现模型及其授权/可否商用，可设默认、删除自定义模型。"""
        import os as _os
        try:
            from live2d_models import list_models_with_meta, remove_model_meta
        except Exception:
            import importlib.util as _ilu
            _p = _ilu.spec_from_file_location(
                "live2d_models", _os.path.join(BASE_DIR, "live2d_models.py"))
            _m = _ilu.module_from_spec(_p)
            _p.loader.exec_module(_m)
            list_models_with_meta, remove_model_meta = _m.list_models_with_meta, _m.remove_model_meta

        dlg = tk.Toplevel(self.root)
        dlg.title("形象管理（模型自定义系统）")
        dlg.geometry("500x380")
        try:
            dlg.transient(self.root)
        except Exception:
            pass

        lb = tk.Listbox(dlg, width=72, height=12)
        lb.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        info = tk.StringVar()
        tk.Label(dlg, textvariable=info, justify="left", anchor="w",
                 wraplength=470).pack(padx=10, fill=tk.X)

        models = list_models_with_meta()
        lb.cur = models
        for name, rel, meta in models:
            tag = "可商用✓" if meta.get("commercial") else "不可商用✗"
            lb.insert(tk.END, f"{name}  [{tag}]  来源:{meta.get('source','?')}  授权:{meta.get('license','?')}")

        def _show(_=None):
            i = lb.curselection()
            if not i:
                return
            _, rel, meta = lb.cur[i[0]]
            info.set("路径: %s\n可商用: %s\n授权: %s\n可删除: %s"
                     % (rel, meta.get("commercial"), meta.get("license"), meta.get("removable")))

        def _set_default():
            i = lb.curselection()
            if not i:
                return
            name, rel, _ = lb.cur[i[0]]
            self._switch_live2d_model(rel, label=name)
            info.set("已设为默认形象（已通知当前窗口，重启后保持）")

        def _delete():
            i = lb.curselection()
            if not i:
                return
            name, rel, meta = lb.cur[i[0]]
            if not meta.get("removable"):
                messagebox.showerror("无法删除", "内置模型不可删除（如需移除请手动删除模型目录）。")
                return
            if not messagebox.askyesno("确认删除", "删除模型「%s」及其文件？" % name):
                return
            dest = _os.path.join(BASE_DIR, rel) if not _os.path.isabs(rel) else rel
            try:
                if _os.path.isdir(dest):
                    import shutil
                    shutil.rmtree(dest)
                remove_model_meta(rel)
                lb.delete(i[0])
                del lb.cur[i[0]]
                info.set("已删除模型「%s」" % name)
            except Exception as e:
                messagebox.showerror("删除失败", str(e))

        lb.bind("<<ListboxSelect>>", _show)
        row = tk.Frame(dlg)
        row.pack(pady=(0, 10))
        tk.Button(row, text="设为默认", command=_set_default, width=12).pack(side=tk.LEFT, padx=6)
        tk.Button(row, text="删除", command=_delete, width=12).pack(side=tk.LEFT, padx=6)
        tk.Button(row, text="关闭", command=dlg.destroy, width=12).pack(side=tk.LEFT, padx=6)

    def _save_pos(self):
        try:
            self.style["pos"] = [self.root.winfo_x(), self.root.winfo_y()]
            self.save_style()
        except Exception:
            pass

    def apply_style(self):
        s = self.style
        try:
            self.root.attributes("-alpha", float(s["alpha"]))
        except Exception:
            pass
        try:
            self.bar.config(bg=s["bg"])
            self.grip.config(bg=s["bg"], fg=s["fg"])
            self.entry.config(bg=s["bg"], fg=s["fg"], insertbackground=self.THEME["accent"])
            self.settings_btn.config(bg=s["bg"], fg=s["fg"])
            self.close_btn.config(bg=s["bg"], fg=s["fg"])
            self.mic_btn.config(bg=s["bg"], fg=s["fg"])
            self.history_btn.config(bg=s["bg"], fg=s["fg"])
            self.voice_status.config(bg=s["bg"], fg=self.THEME["accent2"])
        except Exception:
            pass

    # ---------- 主题与美化辅助 ----------
    THEME = {
        "bg":       "#241f33",
        "panel":    "#2c2540",
        "card":     "#372e54",
        "accent":   "#ff7fb0",   # 主粉
        "accent2":  "#c77dff",   # 副紫
        "text":     "#f3e9ff",
        "muted":    "#a99ec9",
        "entry_bg": "#1c1829",
        "btn":      "#463a66",
        "btn_hot":  "#5a4a82",
        "line":     "#4a3d6b",
    }

    def _panel_header(self, win, title, sub=None):
        """面板顶部标题栏：accent 底色 + 标题 + 副标题。"""
        bar = tk.Frame(win, bg=self.THEME["accent"], height=46)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        tk.Label(bar, text=title, fg="#ffffff", bg=self.THEME["accent"],
                 font=("Microsoft YaHei", 13, "bold")).pack(side=tk.LEFT, padx=14, pady=10)
        if sub:
            tk.Label(bar, text=sub, fg="#ffe3f0", bg=self.THEME["accent"],
                     font=("Microsoft YaHei", 9)).pack(side=tk.LEFT, padx=(6, 0))

    def _hdr(self, parent, title, sub=None):
        """分区标题：左侧彩色圆点 + 粗体标题 + 细分隔线。"""
        f = tk.Frame(parent, bg=self.THEME["panel"])
        f.pack(fill=tk.X, padx=12, pady=(14, 0))
        tk.Label(f, text="●", fg=self.THEME["accent"], bg=self.THEME["panel"],
                 font=("Microsoft YaHei", 8)).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(f, text=title, fg=self.THEME["text"], bg=self.THEME["panel"],
                 font=("Microsoft YaHei", 10, "bold")).pack(side=tk.LEFT)
        if sub:
            tk.Label(f, text=sub, fg=self.THEME["muted"], bg=self.THEME["panel"],
                     font=("Microsoft YaHei", 8)).pack(side=tk.RIGHT)
        sep = tk.Frame(parent, bg=self.THEME["line"], height=1)
        sep.pack(fill=tk.X, padx=12, pady=(3, 8))

    def _flabel(self, parent, text):
        """字段标签（统一配色）。"""
        tk.Label(parent, text=text, fg=self.THEME["muted"], bg=self.THEME["panel"],
                 font=("Microsoft YaHei", 9), anchor="w"
                 ).pack(fill=tk.X, padx=14, pady=(8, 2))

    def _entry(self, parent, textvariable=None, show=None, width=34):
        e = tk.Entry(parent, textvariable=textvariable, show=show, width=width,
                     bg=self.THEME["entry_bg"], fg=self.THEME["text"],
                     insertbackground=self.THEME["accent"],
                     relief=tk.FLAT,
                     highlightbackground=self.THEME["line"], highlightthickness=1,
                     font=("Microsoft YaHei", 10))
        e.pack(padx=14, fill=tk.X)
        return e

    def _btn(self, parent, text, command=None, hot=False, width=None):
        """主题化按钮：扁平 + 悬停高亮 + 手型光标。"""
        b = tk.Button(parent, text=text, command=command,
                      bg=self.THEME["accent"] if hot else self.THEME["btn"],
                      fg="#ffffff" if hot else self.THEME["text"],
                      activebackground=self.THEME["accent"] if hot else self.THEME["btn_hot"],
                      activeforeground="#ffffff",
                      relief=tk.FLAT, borderwidth=0,
                      font=("Microsoft YaHei", 9, "bold"),
                      cursor="hand2")
        if width:
            b.config(width=width)
        def _enter(e):
            b.config(bg=self.THEME["accent"] if hot else self.THEME["btn_hot"])
        def _leave(e):
            b.config(bg=self.THEME["accent"] if hot else self.THEME["btn"])
        b.bind("<Enter>", _enter)
        b.bind("<Leave>", _leave)
        return b

    def _opt(self, parent, var, options, command=None, width=32):
        """主题化下拉菜单。"""
        m = tk.OptionMenu(parent, var, *options, command=command)
        m.config(bg=self.THEME["btn"], fg=self.THEME["text"],
                 activebackground=self.THEME["btn_hot"], activeforeground=self.THEME["text"],
                 relief=tk.FLAT, borderwidth=0,
                 font=("Microsoft YaHei", 9), highlightthickness=0, width=width)
        try:
            m["menu"].config(bg=self.THEME["card"], fg=self.THEME["text"],
                             activebackground=self.THEME["accent"], activeforeground="#fff",
                             relief=tk.FLAT)
        except Exception:
            pass
        m.pack(padx=14, fill=tk.X, pady=(2, 0))
        return m

    def _check(self, parent, text, variable=None, command=None):
        c = tk.Checkbutton(parent, text=text, variable=variable, command=command,
                           bg=self.THEME["panel"], fg=self.THEME["text"],
                           activebackground=self.THEME["panel"],
                           selectcolor=self.THEME["accent"],
                           font=("Microsoft YaHei", 9), anchor="w")
        c.pack(anchor="w", padx=14, pady=(4, 2))
        return c

    def _scale(self, parent, var, frm, to, res, command, length=270):
        s = tk.Scale(parent, from_=frm, to=to, resolution=res, orient=tk.HORIZONTAL,
                     variable=var, length=length, command=command,
                     bg=self.THEME["panel"], fg=self.THEME["muted"],
                     troughcolor=self.THEME["card"], activebackground=self.THEME["accent"],
                     highlightthickness=0, relief=tk.FLAT,
                     font=("Microsoft YaHei", 9), sliderrelief=tk.FLAT, bd=0)
        s.pack(padx=14, fill=tk.X)
        return s

    def _bar_btn(self, parent, text, command, size=11):
        """输入条上的小图标按钮：融合条底色 + 悬停高亮。"""
        b = tk.Button(parent, text=text, command=command,
                      font=("Microsoft YaHei", size), width=2, relief=tk.FLAT,
                      bg=self.style["bg"], fg=self.style["fg"],
                      activebackground=self.THEME["accent"], activeforeground="#fff",
                      cursor="hand2")
        def _enter(e):
            b.config(bg=self.THEME["accent"], fg="#fff")
        def _leave(e):
            b.config(bg=self.style["bg"], fg=self.style["fg"])
        b.bind("<Enter>", _enter)
        b.bind("<Leave>", _leave)
        return b

    def _show_placeholder(self):
        if not self.entry.get():
            self.entry.insert(0, "想跟小念说点什么…")
            self.entry.config(fg=self.THEME["muted"])

    def _clear_placeholder(self):
        if self.entry.get() == "想跟小念说点什么…":
            self.entry.delete(0, tk.END)
            self.entry.config(fg=self.style["fg"])

    def toggle_settings(self):
        if getattr(self, "settings_win", None) and self.settings_win.winfo_exists():
            self.settings_win.destroy()
            self.settings_win = None
            return
        self.open_settings()

    def open_settings(self):
        win = tk.Toplevel(self.root)
        self.settings_win = win
        win.title("输入条设置")
        win.attributes("-topmost", True)
        win.resizable(True, True)
        win.config(bg=self.THEME["panel"])
        try:
            x = self.root.winfo_x() + 20
            y = self.root.winfo_y() - 170
            if y < 0:
                y = 0
            win.geometry(f"280x560+{x}+{y}")
        except Exception:
            pass

        self._panel_header(win, "输入条设置", "小念的悬浮输入条")

        # ---- 滚动容器：Canvas + 右侧 Scrollbar，内容超长时可滚动查看 ----
        canvas = tk.Canvas(win, highlightthickness=0, bg=self.THEME["panel"])
        canvas.configure(yscrollincrement=1)   # 1 单位=1px，确保滚轮 units 模式真正滚动
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview,
                                 bg=self.THEME["card"], troughcolor=self.THEME["panel"])
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scrollbar.set)

        body = tk.Frame(canvas, bg=self.THEME["panel"])
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        # 宽度跟随画布：窗口拉宽时，让内层 body 同步变宽，fill=tk.X 的控件才会撑开
        def _on_canvas_configure(e):
            canvas.itemconfig(body_id, width=e.width)
            canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.bind("<Configure>", _on_canvas_configure)
        # 内层内容变化时也刷新滚动区域
        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # 鼠标滚轮滚动（窗口关闭时解绑，避免影响其它窗口）
        # 步长按 delta 放大（约 40px/格），避免默认 units 模式只滚 1px 几乎看不出
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * event.delta / 3), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        # 延迟刷新滚动区域：等所有控件布局完成后再算一次，保证超长内容可滚
        win.after(60, lambda: canvas.configure(scrollregion=canvas.bbox("all")))

        # ---- 外观 ----
        self._hdr(body, "外观", "透明度 / 音量 / 配色")
        tk.Label(body, text="输入框透明度", fg=self.THEME["muted"], bg=self.THEME["panel"],
                 font=("Microsoft YaHei", 9), anchor="w").pack(fill=tk.X, padx=14, pady=(6, 0))
        alpha_var = tk.DoubleVar(value=self.style["alpha"])
        self._scale(body, alpha_var, 0.3, 1.0, 0.01, lambda v: self._set_alpha(float(v)))
        tk.Label(body, text="语音音量", fg=self.THEME["muted"], bg=self.THEME["panel"],
                 font=("Microsoft YaHei", 9), anchor="w").pack(fill=tk.X, padx=14, pady=(6, 0))
        vol_var = tk.DoubleVar(value=self.style["volume"])
        self._scale(body, vol_var, 0.0, 1.0, 0.05, lambda v: self._set_volume(float(v)))

        # ---- 音频设备 ----
        ins, outs = self.list_audio_devices()
        in_labels = ["（系统默认）"] + [f"{n} (#{i})" for i, n in ins]
        out_labels = ["（系统默认）"] + [f"{n} (#{i})" for i, n in outs]
        self._hdr(body, "音频设备", "语音输入 / 输出")
        self._flabel(body, "麦克风（语音输入）")
        in_var = tk.StringVar(value=self._device_label(self.style.get("input_device", ""), ins))
        self._opt(body, in_var, in_labels,
                  command=lambda v: self._on_input_device_change(v), width=24)
        self._flabel(body, "扬声器（语音输出）")
        out_var = tk.StringVar(value=self._device_label(self.style.get("output_device", ""), outs))
        self._opt(body, out_var, out_labels,
                  command=lambda v: self._on_output_device_change(v), width=24)

        # ---- 对话模型 ----
        self._hdr(body, "对话模型", "运行时切换")
        self._flabel(body, "对话模型")
        mst = self._load_model_state()
        model_var = tk.StringVar(value=mst["current"])
        self._opt(body, model_var, mst["models"],
                  command=lambda v: self._on_model_change(v, mst["models"]), width=22)

        # ---- API / 视觉 / Seed-TTS ----
        self._build_api_section(body)
        self._build_vision_api_section(body)
        self._build_seedtts_section(body)

        # ---- Live2D 形象 ----
        self._hdr(body, "Live2D 形象", "切换桌面形象")
        ld_models = self._discover_live2d_models()
        ld_map = {n: r for n, r in ld_models}
        ld_names = list(ld_map.keys()) or ["（无可用模型）"]
        cur_rel = CONFIG.get("live2d_model", "")
        ld_sel = next((n for n, r in ld_models if r == cur_rel), ld_names[0])
        ld_var = tk.StringVar(value=ld_sel)
        self._opt(body, ld_var, ld_names,
                  command=lambda v: self._on_live2d_model_change(v, ld_map), width=22)
        self._btn(body, "🗂 形象管理", self._open_model_manager, width=24
                  ).pack(anchor="e", padx=14, pady=(4, 0))

        # ---- 配色 ----
        self._hdr(body, "配色", "自定义主题色")
        row = tk.Frame(body, bg=self.THEME["panel"])
        row.pack(pady=(4, 12))
        self._btn(row, "背景色", lambda: self._pick_color("bg"), width=10).pack(side=tk.LEFT, padx=6)
        self._btn(row, "文字色", lambda: self._pick_color("fg"), width=10).pack(side=tk.LEFT, padx=6)

        def _on_close():
            canvas.unbind_all("<MouseWheel>")
            win.destroy()
            setattr(self, "settings_win", None)
        win.protocol("WM_DELETE_WINDOW", _on_close)

    def _set_alpha(self, v):
        self.style["alpha"] = v
        try:
            self.root.attributes("-alpha", v)
        except Exception:
            pass
        self.save_style()

    def _set_volume(self, v):
        self.style["volume"] = v
        if getattr(self, "tts", None) is not None:
            self.tts.volume = v
        self.save_style()

    def _on_input_device_change(self, label):
        """麦克风设备切换：立刻生效（下次录音使用），并持久化到 style。"""
        dev = self._device_value(label)
        self.style["input_device"] = dev
        if getattr(self, "voice", None) is not None:
            self.voice.device = dev
        self.save_style()
        if dev == "":
            self.show_voice_status("麦克风：已切回系统默认")
        else:
            self.show_voice_status(f"麦克风：已切换到 {label}")

    def _on_output_device_change(self, label):
        """扬声器设备切换：立刻生效（下次播放使用），并持久化到 style。"""
        dev = self._device_value(label)
        self.style["output_device"] = dev
        if getattr(self, "tts", None) is not None:
            self.tts.output_device = dev
        self.save_style()
        if dev == "":
            self.show_voice_status("扬声器：已切回系统默认")
        else:
            self.show_voice_status(f"扬声器：已切换到 {label}")

    def _pick_color(self, key):
        _, color = colorchooser.askcolor(initialcolor=self.style[key])
        if not color:
            return
        self.style[key] = color
        self.apply_style()
        self.save_style()

    def send(self):
        if self.assistant is None:
            return
        self._clear_placeholder()
        text = self.entry.get().strip()
        self.entry.delete(0, tk.END)
        self._show_placeholder()
        if not text:
            return
        self.append("你", text)
        # 改为入队：用户连续快速输入时，按输入先后依次生成并播报回复，
        # 避免多条回复并发抢语音、互相打断。
        self._enqueue_user(text)

    def _reply_one(self, text):
        # 用户说“跳/转身”等指令时，立即触发对应动作（不等回复）
        self._send_live2d_action(self._detect_action(text))

        def on_tool(name, args, result):
            self.root.after(0, lambda: self.append(f"🛠 {name}", str(result)[:500]))

        try:
            reply = self.assistant.chat(text, on_tool=on_tool)
        except Exception as e:
            self.root.after(0, lambda: self.append("出错了", str(e)))
            return
        # 文字记录立即显示（用户能马上看到回复）
        self.root.after(0, self._show_reply_text, CONFIG["name"], reply)
        # 语音输出：同步播放，worker 会等它播完再处理下一条，
        # 保证“按输入先后依次输出”，且发声与口型/动作对齐。
        if self.tts.is_ready():
            self._speak(reply)
        elif CONFIG.get("voice_output_enabled"):
            self.root.after(0, lambda: self.show_voice_status(
                "语音输出未配置：请在 .env 填 SEEDTTS_APP_ID / SEEDTTS_ACCESS_KEY，或在设置面板(◐)里配置", 6000))

    def _show_reply_text(self, who, text):
        """仅显示回复文字（用户回复用；语音由调用方同步播放）。"""
        self.append(who, text)

    def _show_reply(self, who, text, proactive=False):
        """显示一条回复文字（并异步播报）。

        proactive=True 表示这是小念“主动”说的内容（看屏正反馈 / 主动关心）。
        优先级规则：当用户正在被回复、或还有未处理的用户提问时，主动内容让位——
        不输出（既不显示气泡也不播报），优先保证用户提问的回复。
        """
        if proactive and self._user_active():
            return
        self.append(who, text)
        if self.tts.is_ready():
            threading.Thread(target=self._speak, args=(text,), daemon=True).start()
        elif CONFIG.get("voice_output_enabled"):
            self.show_voice_status("语音输出未配置：请在 .env 填 SEEDTTS_APP_ID / SEEDTTS_ACCESS_KEY", 6000)

    def _speak(self, text):
        # Seed-TTS 是云端服务，无需本地拉起；直接合成并播放。
        name = CONFIG["name"]
        # on_play：音频开始播放时，气泡+说话动作+进入实时口型模式（与声音起点对齐）
        def on_play():
            self.live2d_say(text, name, start_talk=True)
        # on_level：播放期间每帧把当前音频能量传过去，驱动嘴型实时张合（长句也同步）
        def on_level(rms):
            self._send_mouth(rms)
        # 串行锁：保证所有语音输出（用户回复 / 看屏 / 关心）互不重叠、口型对齐
        with self._speak_lock:
            err = self.tts.speak(text, on_play=on_play, on_level=on_level)
            # 无论成功或失败，播放结束后都归位（口型归零、淡出气泡），避免卡在“张嘴”状态
            self._stop_talk()
        if err:
            self.show_voice_status("🔊 " + err, 6000)

    # ---------- 可见状态提示 ----------
    def show_voice_status(self, msg, ms=3000):
        self.voice_status.config(text=msg)
        self.root.after(ms, lambda: self.voice_status.config(text=""))

    # ---------- 麦克风语音输入（点击切换）----------
    def _mic_toggle(self):
        if not CONFIG.get("voice_input_enabled"):
            self.show_voice_status("语音输入未开启：.env 设 VOICE_INPUT_ENABLED=true", 6000)
            return
        if getattr(self.voice, "_recording", False):
            # 第二次点击：停止并识别
            self.mic_btn.config(text="🎤", relief=tk.FLAT,
                                bg=self.style["bg"], fg=self.style["fg"])
            self.show_voice_status("识别中…", 2000)
            threading.Thread(target=self._mic_recognize, daemon=True).start()
        else:
            # 第一次点击：开始录音
            if self.voice.start():
                self.mic_btn.config(text="⏹", relief=tk.SUNKEN,
                                    bg=self.THEME["accent"], fg="#fff")
                dev_name = getattr(self.voice, "last_device_name", "")
                suffix = f"（设备：{dev_name}）" if dev_name else ""
                self.show_voice_status("🎤 聆听中…再点一下结束" + suffix, 5000)
            else:
                self.show_voice_status("无法打开麦克风，检查设备/权限", 6000)

    def _mic_recognize(self):
        text, level = self.voice.stop()
        if text.startswith("__VOICE_ERR__"):
            msg = "语音识别出错：" + text[len("__VOICE_ERR__"):]
            self.show_voice_status("⚠ " + msg, 8000)
            self.append("系统", "🎤 " + msg)
            return
        if not text:
            if level < 0.005:
                self.append("系统",
                    "🎤 没听到声音：可能是麦克风被其它程序占用，或选错了设备。"
                    "请到设置面板(◐)的「麦克风」下拉里确认选的是你正在说话的那只麦克风。")
                self.show_voice_status("没听到声音，再试一次", 4000)
            else:
                self.append("系统",
                    f"🎤 听到了声音(音量{level:.3f})但没识别出文字，请靠近麦、说清楚一点，"
                    "或到设置面板(◐)换一个麦克风设备试试。")
                self.show_voice_status(f"没识别到文字(音量{level:.3f})，靠近麦/大声点", 5000)
            return
        self.root.after(0, lambda: self._send_voice_text(text))

    def _send_voice_text(self, text):
        self.entry.delete(0, tk.END)
        self.entry.insert(0, text)
        self.entry.config(fg=self.style["fg"])
        self.send()

    def _start_live2d(self):
        try:
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live2d_app.py")
            self.live2d_proc = subprocess.Popen(
                [sys.executable, script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self.append("系统", f"形象窗口未启动：{e}")

    # ---------- 字节 Seed-TTS（云端 AI 音色，非克隆）----------
    def _seedtts_presets(self):
        try:
            from seedtts_presets import SEEDTTS_PRESETS, DEFAULT_VOICE
            return SEEDTTS_PRESETS, DEFAULT_VOICE
        except Exception:
            import importlib.util as _ilu, os as _os
            _p = _ilu.spec_from_file_location(
                "seedtts_presets", _os.path.join(BASE_DIR, "seedtts_presets.py"))
            _m = _ilu.module_from_spec(_p)
            _p.loader.exec_module(_m)
            return _m.SEEDTTS_PRESETS, _m.DEFAULT_VOICE

    def _load_seedtts_voice(self):
        try:
            with open(os.path.join(CONFIG["data_dir"], "seedtts_voice.json"),
                      encoding="utf-8") as f:
                return json.load(f).get("voice", "qingleng_yujie")
        except Exception:
            return CONFIG.get("seedtts_voice", "qingleng_yujie")

    def _save_seedtts_voice(self, key):
        try:
            with open(os.path.join(CONFIG["data_dir"], "seedtts_voice.json"),
                      "w", encoding="utf-8") as f:
                json.dump({"voice": key}, f, ensure_ascii=False)
        except Exception:
            pass

    def _build_seedtts_section(self, parent):
        """在任意面板里插入「Seed-TTS 设置」分区：音色下拉 + App ID + Access Key + 语速 + 测试/保存。"""
        self._hdr(parent, "字节 Seed-TTS", "云端 AI 音色 · 非克隆 · 无侵权")

        # 音色下拉（5 种角色）
        presets, _ = self._seedtts_presets()
        names = [v["name"] for v in presets.values()]
        keys = list(presets.keys())
        cur = self._load_seedtts_voice()
        self._flabel(parent, "Seed-TTS 音色（官方 AI 声线）")
        voice_var = tk.StringVar(value=presets.get(cur, {}).get("name", names[0]))
        self._seedtts_voice_var = voice_var
        self._opt(parent, voice_var, names,
                  command=lambda v: self._on_seedtts_voice_change(
                      keys[names.index(v)] if v in names else keys[0]),
                  width=22)

        self._flabel(parent, "Seed-TTS App ID（火山引擎控制台）")
        aid_var = tk.StringVar(value=CONFIG.get("seedtts_app_id", ""))
        self._entry(parent, textvariable=aid_var)

        self._flabel(parent, "Seed-TTS Access Key（访问控制 → API 密钥）")
        akey_var = tk.StringVar(value=CONFIG.get("seedtts_access_key", ""))
        self._entry(parent, textvariable=akey_var, show="*")

        self._flabel(parent, "语速 (0.5 ~ 2.0)")
        sp_var = tk.DoubleVar(value=float(CONFIG.get("seedtts_speed", 1.0)))
        self._scale(parent, sp_var, 0.5, 2.0, 0.05, lambda v: None)

        row = tk.Frame(parent, bg=self.THEME["panel"])
        row.pack(padx=14, pady=(10, 4))
        self._btn(row, "测试连接",
                  lambda: self._on_seedtts_test(aid_var, akey_var, sp_var, voice_var, keys, names),
                  width=12).pack(side=tk.LEFT, padx=4)
        self._btn(row, "保存并应用",
                  lambda: self._on_seedtts_save(aid_var, akey_var, sp_var, voice_var, keys, names),
                  hot=True, width=12).pack(side=tk.LEFT, padx=4)

    def _on_seedtts_voice_change(self, key):
        self.tts.seedtts_voice = key
        self._save_seedtts_voice(key)
        self.show_voice_status(
            "🎙 已切换 Seed-TTS 音色：" +
            self._seedtts_presets()[0].get(key, {}).get("name", key), 3000)

    def _on_seedtts_test(self, aid_var, akey_var, sp_var, voice_var, keys, names):
        app_id = aid_var.get().strip()
        key = akey_var.get().strip()
        if not app_id or not key:
            self.show_voice_status("请先填写 App ID 和 Access Key", 4000)
            return
        presets, _ = self._seedtts_presets()
        vname = voice_var.get()
        vkey = keys[names.index(vname)] if vname in names else keys[0]
        vid = presets.get(vkey, {}).get("voice_id", vkey)
        self.show_voice_status("正在测试 Seed-TTS 连接…", 2000)

        def _run():
            try:
                from voice import TTS
                t = TTS(enabled=True, backend="seedtts",
                        seedtts_app_id=app_id, seedtts_access_key=key,
                        seedtts_voice=vkey, seedtts_speed=sp_var.get())
                err = t.speak("你好，我是小念，正在测试声音。")
                if err:
                    self.root.after(0, lambda: self.show_voice_status(f"❌ {err[:200]}", 9000))
                else:
                    self.root.after(0, lambda: self.show_voice_status("✅ Seed-TTS 连接成功并已试听", 5000))
            except Exception as e:
                self.root.after(0, lambda: self.show_voice_status(f"❌ {str(e)[:200]}", 9000))
        threading.Thread(target=_run, daemon=True).start()

    def _on_seedtts_save(self, aid_var, akey_var, sp_var, voice_var, keys, names):
        app_id = aid_var.get().strip()
        key = akey_var.get().strip()
        if not app_id or not key:
            self.show_voice_status("⚠ App ID 和 Access Key 不能为空", 4000)
            return
        # 热替换（无需重启）
        self.tts.seedtts_app_id = app_id
        self.tts.seedtts_access_key = key
        self.tts.seedtts_speed = sp_var.get()
        vname = voice_var.get()
        vkey = keys[names.index(vname)] if vname in names else keys[0]
        self.tts.seedtts_voice = vkey
        self._save_seedtts_voice(vkey)
        # 持久化到 .env，下次启动仍生效
        self._write_env_value("SEEDTTS_APP_ID", app_id)
        self._write_env_value("SEEDTTS_ACCESS_KEY", key)
        self._write_env_value("SEEDTTS_VOICE", vkey)
        self._write_env_value("SEEDTTS_SPEED", str(sp_var.get()))
        # 若当前引擎不是 seedtts，切过去
        if self.tts.backend != "seedtts":
            self.tts.backend = "seedtts"
            self._write_env_value("TTS_BACKEND", "seedtts")
        self.show_voice_status("✅ 已保存 Seed-TTS 设置并应用", 5000)

    def _on_close(self):
        """主窗口关闭：先结束形象/语音子进程，再销毁窗口，避免残留。"""
        try:
            if getattr(self, "screen_watcher", None) is not None:
                self.screen_watcher.stop()
        except Exception:
            pass
        for attr in ("live2d_proc",):
            proc = getattr(self, attr, None)
            if proc is not None:
                try:
                    proc.terminate()
                except Exception:
                    pass
        self.root.destroy()

    def live2d_say(self, text, name=None, start_talk=False):
        """向形象窗口发送「气泡 + 说话动作」。

        start_talk=True 时额外带 talk_start 标记，让前端进入实时口型模式
        （锁定当前气泡为说话气泡、口型改由 setMouth 按音频能量驱动），长句也同步。
        """
        if not CONFIG.get("live2d_enabled"):
            return
        name = name or CONFIG["name"]
        try:
            with socket.create_connection(("127.0.0.1", CONFIG["live2d_port"]), timeout=1) as s:
                # 单条消息同时携带气泡文本与“说话”动作标记；接收端一次 recv 后统一处理，
                # 避免两条 sendall 在同一连接上被 TCP 粘包导致 json 解析失败（气泡/动作全丢）。
                payload = {
                    "text": text, "name": name, "motion": True, "args": ["speaking"]
                }
                if start_talk:
                    payload["talk_start"] = True
                s.sendall(json.dumps(payload).encode("utf-8"))
        except Exception:
            pass

    def _send_mouth(self, rms):
        """把当前播放位置的音频能量(0~1)发给形象窗口，驱动实时口型。"""
        if not CONFIG.get("live2d_enabled"):
            return
        try:
            with socket.create_connection(("127.0.0.1", CONFIG["live2d_port"]), timeout=1) as s:
                s.sendall(json.dumps({"mouth": float(rms)}).encode("utf-8"))
        except Exception:
            pass

    def _stop_talk(self):
        """音频播完：通知前端口型归零并淡出气泡。"""
        if not CONFIG.get("live2d_enabled"):
            return
        try:
            with socket.create_connection(("127.0.0.1", CONFIG["live2d_port"]), timeout=1) as s:
                s.sendall(json.dumps({"talk_stop": True}).encode("utf-8"))
        except Exception:
            pass

    def _send_live2d_action(self, act):
        """向形象窗口发送一个动作指令（jump / turn 等）。"""
        if not act or not CONFIG.get("live2d_enabled"):
            return
        try:
            with socket.create_connection(("127.0.0.1", CONFIG["live2d_port"]), timeout=1) as s:
                s.sendall(json.dumps({"action": act}).encode("utf-8"))
        except Exception:
            pass

    def _detect_action(self, text):
        """识别用户话语里的动作意图：跳 / 转身。"""
        t = text or ""
        if any(k in t for k in ("跳", "蹦", "跳一下", "蹦一下", "跳起来")):
            return "jump"
        if any(k in t for k in ("转身", "转个身", "转过去", "转一圈", "转个圈")):
            return "turn"
        return None

    # ---------- 回复队列：用户连续输入时按先后依次输出 ----------
    def _init_reply_queue(self):
        """初始化回复队列与主动关心计时所需的全部状态。"""
        self.user_queue = []
        self.user_q_lock = threading.Lock()
        self.user_q_running = False
        self.busy_with_user = False
        self._speak_lock = threading.Lock()
        self._care_question = ""
        self._care_timer = None
        self._care_retry = None
        self._last_user_activity = time.time()   # 最近一次“用户动作”（输入/切窗）时间
        self._app_chat_exe = None                # 已就“连续使用”搭过话的软件（防同软件重复）
        self._last_idle_care = 0.0               # 上次空闲关心时间（限频，避免刷屏）

    def _enqueue_user(self, text):
        """把一条用户发言放入回复队列，并启动处理 worker（若未运行）。"""
        with self.user_q_lock:
            self.user_queue.append(text)
        self._last_user_activity = time.time()   # 用户发消息 = 一次动作
        self._pump_user_queue()

    def _pump_user_queue(self):
        if self.user_q_running:
            return
        self.user_q_running = True
        threading.Thread(target=self._user_queue_worker, daemon=True).start()

    def _user_queue_worker(self):
        """串行处理用户发言：每次只处理一条，播完再处理下一条。"""
        while True:
            with self.user_q_lock:
                if not self.user_queue:
                    self.user_q_running = False
                    return
                text = self.user_queue.pop(0)
            # 标记“正在回复用户”，期间看屏/主动关心内容一律让位
            self.busy_with_user = True
            try:
                self._schedule_care(text)   # 提问后 6-10 分钟自动触发一次“主动关心”
                self._reply_one(text)
            except Exception as e:
                self.root.after(0, lambda: self.append("出错了", str(e)))
            finally:
                self.busy_with_user = False

    def _user_active(self):
        """用户是否正在被回复，或还有未处理的提问（此时主动内容应让位）。"""
        return self.busy_with_user or bool(self.user_queue)

    # ---------- 主动关心：提问后 6-10 分钟，关联上下文触发 ----------
    def _schedule_care(self, question):
        """在用户提问后 6-10 分钟，自动触发一次与提问内容相关的“主动关心”。

        若期间又有新提问，会重置计时（始终关联最新一次提问）。
        """
        import random
        self._care_question = question
        # 取消上一次计时（含重试计时），避免叠加/串台
        for _t in (self._care_timer, self._care_retry):
            if _t is not None:
                try:
                    _t.cancel()
                except Exception:
                    pass
        self._care_timer = None
        self._care_retry = None
        delay = random.uniform(6 * 60, 10 * 60)   # 6~10 分钟
        self._care_timer = threading.Timer(delay, self._fire_care)
        self._care_timer.daemon = True
        self._care_timer.start()

    def _fire_care(self):
        """触发主动关心。若此刻用户正在被回复，则让位（稍后重试一次），优先保证用户提问。"""
        if self._user_active():
            # 用户正忙：1 分钟后再试一次，不丢关心（不碰 _care_timer，避免误清新计时）
            if self._care_retry is None or not self._care_retry.is_alive():
                self._care_retry = threading.Timer(60, self._fire_care)
                self._care_retry.daemon = True
                self._care_retry.start()
            return
        q = self._care_question
        try:
            msg = self.assistant.care_message(q)
            if msg:
                self.root.after(0, self._show_reply, CONFIG["name"], "（关心）" + msg, True)
        except Exception:
            pass

    # ---------- 并行条件循环：空闲关心 / 软件搭话 ----------
    def start_proactive(self):
        """并行条件循环：根据屏幕信息判断用户状态，主动关心 / 搭话。

        条件1（空闲关心）：用户超过半小时没有任何动作——既没对小念说话，也没切换窗口
            （通过屏幕监控判断）——则基于“当前屏幕内容 + 之前对话”生成关联性关心。
        条件2（软件搭话）：用户连续使用同一款软件超过 10 分钟，则解析屏幕内容主动搭话。

        两条都受优先级规则约束：当用户正在被回复 / 还有待回复的提问时，主动内容让位。
        """
        def loop():
            while True:
                time.sleep(30)   # 每 30 秒轮询一次屏幕状态
                try:
                    self._proactive_tick()
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True).start()

    def _proactive_tick(self):
        """每轮轮询：判断是否满足“空闲关心”或“软件搭话”条件。"""
        watcher = getattr(self, "screen_watcher", None)
        now = time.time()

        # “用户动作”时间 = 最近一次对小念的输入 与 最近一次窗口切换 的较晚者
        last_switch = watcher.current_state()["last_switch"] if watcher else now
        last_action = max(self._last_user_activity, last_switch)
        idle_for = now - last_action

        # —— 条件2：连续使用某款软件 > 10 分钟 → 解析屏幕搭话（每个软件一次）——
        if watcher is not None:
            st = watcher.current_state()
            if st["exe"] and st["dwell_seconds"] >= 10 * 60 and st["exe"] != self._app_chat_exe:
                if self._user_active():
                    return   # 用户正忙，本次不搭话；保留标记以便稍后重试
                self._app_chat_exe = st["exe"]
                self._proactive_app_chat(st)
                return       # 本次循环只处理一个触发，避免并发抢话

        # —— 条件1：超过半小时没有任何动作 → 基于屏幕+历史的关心 ——
        if idle_for >= 30 * 60 and (now - self._last_idle_care) >= 30 * 60:
            self._last_idle_care = now
            self._last_user_activity = now   # 重置空闲计时，避免一直刷
            self._proactive_idle_care(watcher)

    def _screen_context(self, app_name=""):
        """拿到当前屏幕的“客观描述”：视觉可用就截屏看懂，否则用窗口标题/程序名。"""
        ctx = ""
        try:
            import vision
            if vision.is_available():
                desc = vision.describe_screen()
                if desc:
                    ctx = desc
        except Exception:
            ctx = ""
        if not ctx:
            watcher = getattr(self, "screen_watcher", None)
            if watcher is not None:
                st = watcher.current_state()
                t = st.get("title") or ""
                a = st.get("app") or app_name or "某个程序"
                ctx = f"「{a}」" + (f"（窗口标题：{t}）" if t and t != a else "")
            elif app_name:
                ctx = f"「{app_name}」"
        return ctx

    def _proactive_app_chat(self, st):
        """条件2：用户连续使用某软件 >10 分钟，解析屏幕内容主动搭话。"""
        if self._user_active():
            return
        app_name = st.get("app") or "某个程序"
        screen = self._screen_context(app_name)
        try:
            msg = self.assistant.app_chat_message(screen, app_name)
        except Exception:
            return
        if msg:
            self.root.after(0, self._show_reply, CONFIG["name"], "（搭话）" + msg, True)

    def _proactive_idle_care(self, watcher):
        """条件1：用户超过半小时没动作，基于当前屏幕+历史对话关心。"""
        if self._user_active():
            return
        screen = self._screen_context()
        try:
            msg = self.assistant.idle_care_message(screen)
        except Exception:
            return
        if msg:
            self.root.after(0, self._show_reply, CONFIG["name"], "（关心）" + msg, True)

    def start_screen_watch(self):
        """启动屏幕活动监控：看用户在玩什么/用什么软件，适时给正反馈。"""
        self.screen_watcher = None
        if not CONFIG.get("screen_watch_enabled"):
            return
        if self.assistant is None:
            return
        try:
            from screen_watch import ScreenWatcher
        except Exception as e:
            self.append("系统", f"屏幕监控未启动：{e}")
            return

        def on_event(event):
            # 行为信号 → 自主引擎（用于习惯分析与自调参，如深夜久坐提醒更频繁）
            if self.autonomy is not None:
                try:
                    self.autonomy.record_event(event)
                except Exception:
                    pass
            # 收到屏幕活动事件 → 让小念生成一条正反馈并说出来（复用回复管线）
            try:
                msg = self.assistant.screen_feedback(event)
                if msg:
                    self.root.after(0, self._show_reply, CONFIG["name"], "（看屏）" + msg, True)
            except Exception:
                pass

        try:
            self.screen_watcher = ScreenWatcher(
                on_event=on_event,
                interval_sec=CONFIG.get("screen_watch_interval_sec", 5),
                settle_sec=CONFIG.get("screen_watch_settle_sec", 20),
                min_gap_min=CONFIG.get("screen_watch_min_gap_min", 10),
                milestones_min=CONFIG.get("screen_watch_milestones", (30, 60, 120)),
                capture=CONFIG.get("screen_capture_enabled", False),
                data_dir=CONFIG.get("data_dir", "."),
                ignore=CONFIG.get("screen_watch_ignore", []),
                self_names=[CONFIG.get("name", "小念")],
            )
            self.screen_watcher.start()
        except Exception as e:
            self.append("系统", f"屏幕监控启动失败：{e}")

    # ---------- 自主权限：GUI 侧回调（确认弹窗 / 提示 / 参数生效）----------
    def request_confirm(self, title, message):
        """后台线程里请求用户确认（弹窗）。无 gui / 超时 → 安全拒绝。

        必须在主线程弹 messagebox，故用 after(0,...) 派发，再用 Event 等结果；
        超时（默认 180s 无应答）按“拒绝”处理，保证 fail-safe。
        """
        ev = threading.Event()
        ans = {}

        def popup():
            try:
                ans["v"] = messagebox.askyesno(title, message, parent=self.root)
            except Exception:
                ans["v"] = False
            ev.set()

        try:
            self.root.after(0, popup)
        except Exception:
            return False
        ev.wait(timeout=180)
        return bool(ans.get("v", False))

    def autonomy_toast(self, msg, ms=6000):
        """小念自主调整时的轻提示（复用语音状态条，自动消失）。"""
        self.show_voice_status(msg, ms)

    def update_screen_watch_params(self):
        """把最新 CONFIG 推给运行中的屏幕监控器，使自主调过的参数即时生效。"""
        w = getattr(self, "screen_watcher", None)
        if w is None:
            return
        try:
            w.interval = max(2, int(CONFIG.get("screen_watch_interval_sec", 5)))
            w.settle_sec = max(5, int(CONFIG.get("screen_watch_settle_sec", 20)))
            w.min_gap = max(30.0, float(CONFIG.get("screen_watch_min_gap_min", 10)) * 60.0)
            w.milestones = sorted(set(
                int(m) for m in CONFIG.get("screen_watch_milestones", (30, 60, 120)) if int(m) > 0
            ))
        except Exception:
            pass

    def on_autonomy_changed(self, key):
        """自主引擎改完参数后的回调：屏幕相关项即时推给监控器。"""
        if key is None or key.startswith("screen_watch_"):
            self.update_screen_watch_params()

    # ---------- 接收 live2d 窗口反向指令（输入框显隐等）----------
    def start_control_server(self):
        port = int(CONFIG.get("gui_control_port", 9744))
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", port))
            srv.listen(4)
        except Exception as e:
            self.append("系统", f"控制服务未启动：{e}")
            return

        def loop():
            while True:
                try:
                    conn, _ = srv.accept()
                    data = conn.recv(65536).decode("utf-8", "ignore")
                    conn.close()
                    if not data:
                        continue
                    try:
                        msg = json.loads(data)
                    except Exception:
                        continue
                    if msg.get("toggle_input"):
                        self.root.after(0, self._toggle_input_visibility)
                except Exception:
                    continue

        threading.Thread(target=loop, daemon=True).start()

    def _toggle_input_visibility(self):
        """由 live2d 窗口的「输入框」按钮切换输入条显隐。"""
        try:
            if self.root.state() == "withdrawn":
                self.root.deiconify()
                try:
                    self.root.lift()
                    self.root.attributes("-topmost", CONFIG["input_topmost"])
                except Exception:
                    pass
                self.entry.focus_set()
            else:
                self.root.withdraw()
        except Exception:
            pass

    # ---------- 全局快捷键（Ctrl+Alt+V 语音 / Ctrl+Alt+G 控制台）----------
    def start_hotkeys(self):
        """注册两个全局热键（同一线程，避免重复与跨线程丢消息）：
           Ctrl+Alt+V -> 触发语音输入；Ctrl+Alt+G -> 开关“小念控制台”。
        关键修复（两个都会让热键彻底失灵，已修）：
        1) RegisterHotKey 的 hWnd 必须传 NULL(0)，不能传 HWND_MESSAGE(-3)，
           否则本机返回 1400(INVALID_WINDOW_HANDLE) 注册失败、两个键都没反应。
        2) 注册和 GetMessageW 消息泵必须在【同一个线程】里：
           RegisterHotKey 会把 WM_HOTKEY 投递到「注册它的那个线程」的消息队列，
           若在主线程注册、却在守护线程取消息，主线程被 tkinter 占着，
           守护线程永远等不到 -> 必须在这里的 loop 线程里一并注册。
        """
        if os.name != "nt":
            return
        try:
            import ctypes
            import ctypes.wintypes   # 必须显式导入子模块，否则 ctypes.wintypes.MSG 报 AttributeError
            user32 = ctypes.windll.user32
        except Exception:
            return
        MOD_CTRL, MOD_ALT, MOD_NOREPEAT = 0x0002, 0x0001, 0x4000
        VK_V, VK_G = 0x56, 0x47
        WM_HOTKEY = 0x0312

        def loop():
            try:
                # 注册 + 消息泵同线程（hWnd 用 NULL=0，绝不用 HWND_MESSAGE）
                ok_v = user32.RegisterHotKey(0, 1, MOD_CTRL | MOD_ALT | MOD_NOREPEAT, VK_V)
                ok_c = user32.RegisterHotKey(0, 2, MOD_CTRL | MOD_ALT | MOD_NOREPEAT, VK_G)
                if not ok_v or not ok_c:
                    # 注册失败大多是该组合键已被其它程序占用（错误码 1400/1401/1402）
                    try:
                        with open(os.path.join(CONFIG["data_dir"], "hotkey.log"),
                                  "a", encoding="utf-8") as f:
                            f.write(f"[hotkey] 注册失败：Ctrl+Alt+V={ok_v} Ctrl+Alt+G={ok_c} "
                                    f"（可能被其它软件占用，需更换快捷键）\n")
                    except Exception:
                        pass
                msg = ctypes.wintypes.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == WM_HOTKEY:
                        if msg.wParam == 1:
                            self.root.after(0, self._mic_toggle)
                        elif msg.wParam == 2:
                            self.root.after(0, self.toggle_console)
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
            except Exception:
                pass

        threading.Thread(target=loop, daemon=True).start()

    def toggle_console(self):
        if getattr(self, "console_win", None) and self.console_win.winfo_exists():
            self.console_win.destroy()
            self.console_win = None
            return
        self.open_console()

    def set_input_visible(self, visible):
        """直接设定输入条显隐（控制台复选框用，避免 toggle 的二义性）。"""
        try:
            if visible:
                self.root.deiconify()
                self.root.lift()
                self.root.attributes("-topmost", CONFIG["input_topmost"])
                self.entry.focus_set()
            else:
                self.root.withdraw()
        except Exception:
            pass

    def _send_live2d_msg(self, msg):
        """向形象窗口发送一条控制指令（大小/气泡/复位等）。"""
        if not CONFIG.get("live2d_enabled"):
            return
        try:
            with socket.create_connection(("127.0.0.1", CONFIG["live2d_port"]), timeout=1) as s:
                s.sendall(json.dumps(msg).encode("utf-8"))
        except Exception:
            pass

    def _send_live2d_scale(self, v):
        self._send_live2d_msg({"scale": float(v)})

    def _send_live2d_bubble(self, on):
        self._send_live2d_msg({"bubble": bool(on)})

    def _send_live2d_reset(self):
        self._send_live2d_msg({"reset": True})

    def open_console(self):
        """整合控制台：一个窗口控制小念的所有参数。整体放进可滚动区域，
        窗口放大且可拖拽缩放，避免功能显示不全。"""
        win = tk.Toplevel(self.root)
        self.console_win = win
        win.title(f"{CONFIG['name']} · 控制台")
        win.attributes("-topmost", True)
        win.resizable(True, True)
        win.config(bg=self.THEME["panel"])
        try:
            x = self.root.winfo_x() + 20
            y = self.root.winfo_y() - 20
            if y < 0:
                y = 0
            win.geometry(f"330x640+{x}+{y}")
            win.minsize(290, 380)
        except Exception:
            pass

        self._panel_header(win, f"{CONFIG['name']} · 控制台", "全局掌控小念")

        # ---- 滚动容器：Canvas + 右侧滚动条 + 内层 frame ----
        canvas = tk.Canvas(win, highlightthickness=0, bg=self.THEME["panel"])
        canvas.configure(yscrollincrement=1)   # 1 单位=1px，确保滚轮 units 模式真正滚动
        scroll = tk.Scrollbar(win, orient="vertical", command=canvas.yview,
                              bg=self.THEME["card"], troughcolor=self.THEME["panel"])
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        body = tk.Frame(canvas, bg=self.THEME["panel"])
        canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # 滚轮滚动（窗口关闭时解绑，避免影响其它窗口）
        # 步长按 delta 放大（约 40px/格），避免默认 units 模式只滚 1px 几乎看不出
        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * event.delta / 3), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)
        # 延迟刷新滚动区域：等所有控件布局完成后再算一次，保证超长内容可滚
        win.after(60, lambda: canvas.configure(scrollregion=canvas.bbox("all")))

        def _on_close():
            canvas.unbind_all("<MouseWheel>")
            win.destroy()
            setattr(self, "console_win", None)
        win.protocol("WM_DELETE_WINDOW", _on_close)

        tk.Label(body, text="快捷键 Ctrl+Alt+G 开关此面板",
                 fg=self.THEME["muted"], bg=self.THEME["panel"],
                 font=("Microsoft YaHei", 9)).pack(pady=(8, 2))

        # ---- 桌面形象 ----
        self._hdr(body, "桌面形象", "大小 / 气泡 / 显隐")
        tk.Label(body, text="模型大小", fg=self.THEME["muted"], bg=self.THEME["panel"],
                 font=("Microsoft YaHei", 9), anchor="w").pack(fill=tk.X, padx=14, pady=(6, 0))
        scale_var = tk.DoubleVar(value=1.0)
        self._scale(body, scale_var, 0.3, 2.2, 0.01, lambda v: self._send_live2d_scale(float(v)))
        self._btn(body, "复位模型大小/位置", self._send_live2d_reset, width=28
                  ).pack(pady=(4, 2))

        input_var = tk.BooleanVar(value=(self.root.state() != "withdrawn"))
        self._check(body, "显示输入框", variable=input_var,
                    command=lambda: self.set_input_visible(input_var.get()))
        bubble_var = tk.BooleanVar(value=True)
        self._check(body, "显示对话气泡", variable=bubble_var,
                    command=lambda: self._send_live2d_bubble(bubble_var.get()))

        # ---- 输入条与语音 ----
        self._hdr(body, "输入条与语音", "透明度 / 音量")
        tk.Label(body, text="输入框透明度", fg=self.THEME["muted"], bg=self.THEME["panel"],
                 font=("Microsoft YaHei", 9), anchor="w").pack(fill=tk.X, padx=14, pady=(6, 0))
        alpha_var = tk.DoubleVar(value=self.style["alpha"])
        self._scale(body, alpha_var, 0.3, 1.0, 0.01, lambda v: self._set_alpha(float(v)))
        tk.Label(body, text="语音音量", fg=self.THEME["muted"], bg=self.THEME["panel"],
                 font=("Microsoft YaHei", 9), anchor="w").pack(fill=tk.X, padx=14, pady=(6, 0))
        vol_var = tk.DoubleVar(value=self.style["volume"])
        self._scale(body, vol_var, 0.0, 1.0, 0.05, lambda v: self._set_volume(float(v)))

        # ---- 对话模型 ----
        self._hdr(body, "对话模型", "运行时切换")
        self._flabel(body, "对话模型")
        mst = self._load_model_state()
        model_var = tk.StringVar(value=mst["current"])
        self._opt(body, model_var, mst["models"],
                  command=lambda v: self._on_model_change(v, mst["models"]), width=32)

        # ---- API / 视觉 / Seed-TTS ----
        self._build_api_section(body)
        self._build_vision_api_section(body)
        self._build_seedtts_section(body)

        # ---- Live2D 形象 ----
        self._hdr(body, "Live2D 形象", "切换桌面形象")
        ld_models = self._discover_live2d_models()
        ld_map = {n: r for n, r in ld_models}
        ld_names = list(ld_map.keys()) or ["（无可用模型）"]
        cur_rel = CONFIG.get("live2d_model", "")
        ld_sel = next((n for n, r in ld_models if r == cur_rel), ld_names[0])
        ld_var = tk.StringVar(value=ld_sel)
        self._opt(body, ld_var, ld_names,
                  command=lambda v: self._on_live2d_model_change(v, ld_map), width=32)

        # ---- 小念的自主权限（受约束自调参）----
        self._hdr(body, "小念的自主权限", "受约束自调参")
        a_status = tk.Label(
            body,
            text=("已开启（在白名单内自调参，大改动会先问你）"
                  if (self.autonomy and self.autonomy.enabled) else "已关闭（改动全由你定）"),
            fg="#2e7d32" if (self.autonomy and self.autonomy.enabled) else "#c62828",
            bg=self.THEME["panel"],
            font=("Microsoft YaHei", 9), wraplength=280, justify="left",
        )
        a_status.pack(anchor="w", padx=14)

        def _review_changes():
            if self.autonomy is None:
                return
            txt = self.autonomy.review()
            messagebox.showinfo(f"{CONFIG['name']} 的自主改动", txt, parent=self.root)

        def _reset_changes():
            if self.autonomy is None:
                return
            if messagebox.askyesno("撤销小念的改动",
                                   "确定要撤销小念所有自主调整、恢复你的基线设置吗？",
                                   parent=self.root):
                self.autonomy.reset_all()
                a_status.config(text="已关闭（改动全由你定）", fg="#c62828")

        def _toggle_autonomy():
            if self.autonomy is None:
                return
            on = not self.autonomy.enabled
            self.autonomy.set_mode(on)
            a_status.config(
                text=("已开启（在白名单内自调参，大改动会先问你）" if on
                      else "已关闭（改动全由你定）"),
                fg="#2e7d32" if on else "#c62828",
            )

        a_row = tk.Frame(body, bg=self.THEME["panel"])
        a_row.pack(pady=(6, 2))
        self._btn(a_row, "查看改动", _review_changes, width=12).pack(side=tk.LEFT, padx=6)
        self._btn(a_row, "撤销全部", _reset_changes, width=12).pack(side=tk.LEFT, padx=6)
        self._btn(body, "开关自主权限", _toggle_autonomy, width=28, hot=True).pack(pady=(4, 6))
        tk.Label(body,
                 text="小念只在白名单内改配置文件，绝不碰系统/代码/你的文件；"
                      "作息类大调整会弹窗问你。",
                 fg=self.THEME["muted"], bg=self.THEME["panel"],
                 font=("Microsoft YaHei", 8), wraplength=280,
                 justify="left").pack(anchor="w", padx=14, pady=(0, 4))

        # ---- 动作 ----
        self._hdr(body, "动作", "让小念动起来")
        row = tk.Frame(body, bg=self.THEME["panel"])
        row.pack(pady=(6, 12))
        self._btn(row, "跳一下", lambda: self._send_live2d_action("jump"), width=11
                  ).pack(side=tk.LEFT, padx=8)
        self._btn(row, "转个身", lambda: self._send_live2d_action("turn"), width=11
                  ).pack(side=tk.LEFT, padx=8)

    def notify(self, msg):
        win = tk.Toplevel(self.root)
        win.title(CONFIG["name"])
        win.attributes("-topmost", True)
        win.geometry("320x130")
        tk.Label(win, text=f"{CONFIG['name']} 想你啦 💕", font=("Microsoft YaHei", 12, "bold")).pack(pady=6)
        tk.Label(win, text=msg, wraplength=290, font=("Microsoft YaHei", 10)).pack(pady=6)
        tk.Button(win, text="好的", command=win.destroy).pack(pady=4)
        win.after(8000, win.destroy)
