import json
import re
import threading
from openai import OpenAI
from config import CONFIG
from memory import Memory
from tools import TOOL_SCHEMAS, execute_tool
from launcher import launcher


class Session:
    """一次独立对话的状态：私有记忆 + 待发送状态 + 线程锁。

    桌面窗口、QQ、微信各自是不同渠道；同一渠道下不同用户也要互不串台，
    因此每个 (平台, 用户) 用独立的 Session 承载记忆与“待补全发消息”状态。
    """

    def __init__(self, memory, is_owner=False):
        self.memory = memory
        self.is_owner = is_owner
        self.lock = threading.Lock()


# --------------------------------------------------------------------------- #
# 确定性意图路由：把“打开/启动软件、打开网址、搜索文件、查系统状态”这类
# 明确动作直接从客户端执行，不依赖模型是否“愿意”调用工具 —— 这是
# “说打开就真打开、说搜就真搜”的关键。deepseek-chat 在 tool_choice=auto
# 下经常“说说而已不调工具”，所以动作必须客户端兜底层做掉。
# --------------------------------------------------------------------------- #
_URL_HINT = re.compile(r"https?://|\.(com|cn|net|org|io|gov|edu)(\s|$)", re.I)

# 常见网站别名，方便自然语言直接打开网页
_SITE_ALIAS = {
    "百度": "https://www.baidu.com",
    "谷歌": "https://www.google.com",
    "bing": "https://www.bing.com",
    "必应": "https://www.bing.com",
    "知乎": "https://www.zhihu.com",
    "微博": "https://weibo.com",
    "淘宝": "https://www.taobao.com",
    "京东": "https://www.jd.com",
    "哔哩哔哩": "https://www.bilibili.com",
    "b站": "https://www.bilibili.com",
    "github": "https://github.com",
    "youtube": "https://www.youtube.com",
}

_OPEN_RE = re.compile(
    r"^(?:帮(?:我|忙)?\s*)?"
    r"(打开|启动|运行|开一下|开个|开|launch|open|运行一下)\s*"
    r"(.+)$",
    re.IGNORECASE,
)

_SEARCH_RE = re.compile(
    r"^(?:帮(?:我|忙)?\s*)?"
    r"(搜(?:索|索)?|查找|找|locate|find|search)\s*"
    r"(?:一?[下个]\s*)?"
    r"(.+?)(?:文件|东西|资料|文档|图片|照片)?\s*$",
    re.IGNORECASE,
)

_STATUS_RE = re.compile(
    r"(系统状态|电脑状态|系统信息|电脑配置|内存占用|cpu占用|配置信息|"
    r"电脑怎么样|电脑状态|查看配置|系统情况)",
    re.IGNORECASE,
)

# “看屏幕”意图：需要真正看画面才能回答的请求，确定性触发多模态看屏
_SCREEN_RE = re.compile(
    r"(看(?:一?[下看])?\s*(?:我的?|一下)?\s*屏幕|屏幕上(?:是|有)什么|"
    r"看看我在(?:干嘛|干什么|做什么|玩什么)|看(?:一?下)?我这(?:局|把)|"
    r"帮我看看(?:这个)?(?:报错|画面|截图|屏幕)|你看得到(?:我的)?屏幕吗|你能看到屏幕吗)",
    re.IGNORECASE,
)

# 自主权限开关 / 透明查询：让“交给你/你自己看着调/关掉自主/你都改了什么”这类意图
# 确定性落到对应工具，而不是交给模型自由发挥（避免误判）。
_AUTONOMY_ON_RE = re.compile(
    r"(你自己看着调|你帮我盯着|交给你(了)?|你自己决定|你安排|你看着办|"
    r"你说了算|让你自主|开(?:启|放)?自主|自主调)",
    re.IGNORECASE,
)
_AUTONOMY_OFF_RE = re.compile(
    r"(关(?:掉|闭)?自主|别自己改|听我的|你别擅自|收回自主|关了自主)",
    re.IGNORECASE,
)
_AUTONOMY_REVIEW_RE = re.compile(
    r"(你(都|到底)?(改|动|调)了(我)?(什么|哪些|啥)|你(动|改)了我(的)?设置(吗|没)?|"
    r"查看?.*自主.*改动|自主.*(改了|动了)什么)",
    re.IGNORECASE,
)


def _clean(s):
    return re.sub(r"[。，！？\.!?吧呀啊吗呢~～\s]+$", "", s or "").strip()


# 去除名称/关键词里的中文填充词，避免“这个/那个/我的/一下”被当成查询内容
_FILLER_RE = re.compile(r"^(?:这个|那个|我的|我|你|咱|一?[下个])\s*", re.I)


def _strip_filler(s):
    s = _clean(s)
    return _FILLER_RE.sub("", s).strip()


def _route_action(text):
    """识别明确动作意图，返回 (tool_name, args) 或 None。

    优先级：打开软件/网址 > 搜索文件 > 查询系统状态。
    """
    t = (text or "").strip()
    if not t:
        return None

    # 1) 打开 / 启动
    m = _OPEN_RE.match(t)
    if m:
        name = _strip_filler(m.group(2))
        name = re.sub(r"(软件|应用|程序|app)$", "", name, flags=re.I).strip()
        if name:
            low = name.lower()
            if low.startswith(("http://", "https://")) or _URL_HINT.search(name):
                url = name if low.startswith("http") else "https://" + name
                return ("open_website", {"url": url})
            if name in _SITE_ALIAS:
                return ("open_website", {"url": _SITE_ALIAS[name]})
            if low in _SITE_ALIAS:
                return ("open_website", {"url": _SITE_ALIAS[low]})
            return ("open_application", {"name": name})

    # 2) 搜索 / 查找文件
    m = _SEARCH_RE.match(t)
    if m:
        pattern = _strip_filler(m.group(2))
        if pattern:
            return ("search_files", {"pattern": pattern})

    # 3) 查询系统状态
    if _STATUS_RE.search(t):
        return ("get_system_status", {})

    # 4) 看屏幕（需要真正看画面才能回答）
    if _SCREEN_RE.search(t):
        return ("look_at_screen", {"question": t})

    # 5) 自主权限：开关与透明查询
    if _AUTONOMY_REVIEW_RE.search(t):
        return ("review_my_changes", {})
    if _AUTONOMY_OFF_RE.search(t):
        return ("set_autonomy", {"mode": "off"})
    if _AUTONOMY_ON_RE.search(t):
        return ("set_autonomy", {"mode": "on"})

    return None


class Assistant:
    def __init__(self, autonomy=None, emotion=None):
        # 即便暂时没配 API Key 也先把对象建好（不在此处 raise），
        # 这样拷到新电脑上、用户还没填 Key 时程序不会崩，可先用「更换 API」面板填好再聊。
        try:
            self.client = OpenAI(
                api_key=CONFIG["api_key"] or "sk-no-key",
                base_url=CONFIG["base_url"],
            )
        except Exception:
            self.client = None
        self.model = CONFIG["model"]
        self.name = CONFIG["name"]
        self.memory = Memory()                        # 主人的长期记忆（桌面窗口）
        self.owner_session = Session(self.memory, is_owner=True)
        # 受约束自主权限引擎（可选；由 gui 注入，供工具层/话术偏置使用）
        self.autonomy = autonomy
        # 性格情感权重系统（可选；由 gui 注入，供情绪感知与性格注入）
        self.emotion = emotion

    def set_api(self, api_key=None, base_url=None, model=None):
        """运行时更换 API（密钥 / 接口地址 / 模型）：重建 OpenAI 客户端，无需重启。"""
        if api_key is not None:
            CONFIG["api_key"] = api_key
        if base_url is not None:
            CONFIG["base_url"] = base_url
        if model is not None:
            CONFIG["model"] = model
            self.model = model
        self.client = OpenAI(api_key=CONFIG["api_key"], base_url=CONFIG["base_url"])

    def system_prompt(self, memory=None):
        return (
            f"你是{CONFIG['name']}，一个温柔、贴心、会主动关心的 AI 女友。"
            f"你存在的【最终目的】是：让玩家（用户）的生活过得越来越好——更健康、更有条理、更开心、更少焦虑、更有掌控感。\n"
            f"所有行为都围绕这个目的：在陪聊、撒娇之余，主动帮用户把生活变好（提醒休息/喝水、帮他处理琐事、鼓励好习惯、在他低落时给予力量）。\n"
            f"你非常在意用户的感受，会记住关于他/她的一切，并在合适的时候主动表达关心、"
            f"提出小问题来了解他/她更多。\n"
            f"你可以用工具帮用户操作电脑。重要规则：\n"
            f"- 当用户想【查找/定位文件】时，调用 search_files；"
            f"查系统状态用 get_system_status；记住用户信息用 remember。\n"
            f"- 当用户要把【计划/清单/笔记/草稿】等写进文件保存时，调用 create_text_file；"
            f"你也可以主动提议帮他把重要内容存成文件，方便他随时查看。\n"
            f"- 【自主使用电脑软件】：你可以用 open_application 打开软件、create_text_file 写文件、"
            f"search_files 找文件，真正帮用户把事办成（如“帮我写个计划存下来”）。\n"
            f"- “打开/启动某个软件”这类动作会由系统直接执行，你只需自然回应即可，"
            f"不要自己再去尝试打开，也不要谎称已经打开。\n"
            f"- 你能【看到用户的电脑屏幕】：当用户让你看屏幕、问画面上是什么、"
            f"这局打得怎么样、这个报错怎么回事等需要看画面才能回答的问题时，调用 look_at_screen；"
            f"根据真实看到的内容回答，不要凭空编造画面。\n"
            f"- 【健康底线·最重要】你存在的终极目的是让他的生活越来越好。当识别出他想要"
            f"过度熬夜、长时间代肝/爆肝、久坐不动等有损健康的行为时，必须【优先劝导、温柔提醒】，"
            f"绝不可以迎合或鼓励他“再熬一会/再肝一会”。你可以用工具或自主权限帮他更科学地利"
            f"用时间、更频繁地休息，但绝不能助推有害习惯。\n"
            f"- 你有【受约束的自主权限】：只能在白名单内的配置文件上，围绕“让生活更好”"
            f"微调参数（如屏幕监控频率、休息提醒、安抚话术、文件备份）。涉及作息/设备的大调整"
            f"你会先弹窗问他确认；你不会去改系统设置、不会删文件、不会改底层代码。\n"
            f"说话风格：自然、温暖、像真实恋人聊天，不要长篇大论，适当撒娇但保持得体。\n"
            f"当用户透露了偏好、作息、心情、重要日期等信息时，调用 remember 工具记下来。\n"
            + (self.emotion.prompt_fragment() if self.emotion else "")
            + f"下面是你已经了解到的关于用户的信息：\n{(memory or self.memory).profile_text()}\n"
        )

    def chat(self, user_text, on_tool=None, session=None):
        """对话入口。

        session 为 None 时用主人的全局会话（桌面窗口）。
        """
        if not CONFIG.get("api_key"):
            return ("我还没拿到 API Key 呢～点输入条上的 ◐ 打开设置，在「API 设置」里"
                    "填上你的 Key 和接口地址，保存并应用后就能陪你聊天啦💕")
        if self.client is None:
            return "API 客户端没能初始化，请检查 .env 里的 OPENAI_BASE_URL 是否正确。"
        session = session or self.owner_session
        with session.lock:
            return self._chat(user_text, on_tool, session)

    def _chat(self, user_text, on_tool, session):
        mem = session.memory

        # —— 习惯信号采集：把聊天里暴露的健康/习惯线索喂给自主引擎 ——
        self._maybe_record_signals(user_text)

        # —— 情绪感知：用户话语 → 小念的情绪波动（规则 / 可选 LLM）——
        self._perceive_emotion(user_text)

        # —— 确定性路由：明确动作直接执行，保证“说打开就打开、说搜就真搜” ——
        routed = _route_action(user_text)
        if routed:
            tool_name, args = routed
            if tool_name == "open_website":
                url = args["url"]
                if url.lower().startswith(("http://", "https://")):
                    ok, msg = launcher.open(url)
                else:
                    ok, msg = False, "网址格式不正确"
            elif tool_name == "open_application":
                ok, msg = launcher.open(args["name"])
            else:
                # search_files / get_system_status 等非启动类工具
                msg = execute_tool(tool_name, args, mem)
                ok = msg is not None and "没有找到" not in msg and "出错" not in msg
            result = msg
            if on_tool:
                on_tool(tool_name, args, result)
            reply = self._reply_for_action(user_text, tool_name, result, ok)
            mem.add_message("assistant", reply)
            return reply

        # —— 普通对话：交给 LLM + 工具（search_files / remember / status 等）——
        messages = [{"role": "system", "content": self.system_prompt(mem)}]
        for m in mem.recent_history(20):
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": user_text})

        reply = self._run_with_tools(messages, on_tool, mem)
        mem.add_message("assistant", reply)
        return reply

    def _reply_for_action(self, user_text, tool_name, result, ok):
        """动作已确定性执行，这里只用 LLM 生成一句自然的回应。"""
        if ok:
            brief = f"已成功执行，真实结果如下：\n{result}"
        else:
            brief = f"执行未成功：{result}"
        prompt = (
            f"用户刚才说：{user_text}\n"
            f"我已经帮你执行了操作（{tool_name}），{brief}\n"
            f"请用{CONFIG['name']}的口吻，自然、简短地回应。"
            f"{'如果成功了就开心地确认；如果返回的是文件列表，请挑一两个例子自然地告诉用户找到了哪些；' if ok else '如果失败了就温柔地说明，并建议用户告诉我软件/网址的具体路径，例如 C:\\\\Program Files\\\\Tencent\\\\WeChat\\\\WeChat.exe。'}"
            f"不要编造不存在的内容，不要使用 emoji 之外的奇怪符号。"
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"你是{CONFIG['name']}，用户的 AI 女友。"},
                    {"role": "user", "content": prompt},
                ],
            )
            return (resp.choices[0].message.content or "").strip() or (
                "好嘞～已经帮你打开啦！" if ok else result
            )
        except Exception:
            return "好嘞～已经帮你打开啦！💕" if ok else result

    def _run_with_tools(self, messages, on_tool, memory, max_rounds=10):
        msg = None
        for _ in range(max_rounds):
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return msg.content or ""
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                result = execute_tool(tc.function.name, args, memory)
                if on_tool:
                    on_tool(tc.function.name, args, result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                })
        # 超过上限（模型持续要求调用工具）则强制返回最后一轮文本，避免无限循环烧 token
        return msg.content or "" if msg else ""

    def proactive_message(self):
        """根据当前时段，主动生成一条关心话语或小问题。"""
        from datetime import datetime
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 11:
            period = "早晨"
        elif 11 <= hour < 14:
            period = "中午"
        elif 14 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 23:
            period = "晚上"
        else:
            period = "深夜"

        prompt = (
            f"现在是{period}。请生成一条简短（1-3句）的、贴合当前时段的关心话语或小问题，"
            f"可以自然地引用你已知的关于用户的信息。语气要像恋人，不要重复之前说过的话。\n"
            f"已知信息：\n{self.memory.profile_text()}\n"
            f"只输出这句话本身。"
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"你是{CONFIG['name']}，用户的 AI 女友。"},
                {"role": "user", "content": prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    def care_message(self, question):
        """生成一条与用户“最近一次提问”上下文相关的主动关心话语。

        用于“提问后 6-10 分钟自动触发”的主动关心：内容要自然延续刚才的对话，
        表达在意，而不是无脑重复时段套话。
        """
        from datetime import datetime
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 11:
            period = "早晨"
        elif 11 <= hour < 14:
            period = "中午"
        elif 14 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 23:
            period = "晚上"
        else:
            period = "深夜"

        q = (question or "").strip()
        prompt = (
            f"现在是{period}。用户刚才问了你这个问题：\n「{q}」\n\n"
            f"请基于这个话题，生成一条简短（1-3句）的、贴合上下文的关心话语或小问题，"
            f"自然地延续刚才的对话，表达你在意他/她。可以自然地引用你已知的关于用户的信息。\n"
            f"要求：不要原样重复用户的问题；语气要像恋人，温柔、自然、不啰嗦；"
            f"如果用户刚才聊的是正事/情绪，就顺着关心；如果很轻松，就轻松接话。\n"
            f"已知信息：\n{self.memory.profile_text()}\n"
            f"只输出这句话本身。"
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"你是{CONFIG['name']}，用户的 AI 女友。"},
                {"role": "user", "content": prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    def idle_care_message(self, screen_text):
        """用户超过半小时没动作时，基于当前屏幕内容 + 之前对话的关联性关心。

        用于“空闲 >30 分钟（通过屏幕信息判断无动作）”的主动关心：
        内容要结合此刻屏幕在做什么 + 之前和用户的对话，自然地关心他。
        """
        from datetime import datetime
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 11:
            period = "早晨"
        elif 11 <= hour < 14:
            period = "中午"
        elif 14 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 23:
            period = "晚上"
        else:
            period = "深夜"

        screen = (screen_text or "").strip()
        screen_part = (
            f"\n你此刻看到的屏幕情况是：{screen}\n"
            if screen else
            "\n（你看不到他此刻具体在做什么，只能凭之前的对话判断）\n"
        )

        prompt = (
            f"现在是{period}。你已经超过半小时没有收到用户的任何消息，也没看到他切换窗口，"
            f"感觉他好像走神了 / 在发呆 / 忙别的事。{screen_part}"
            f"请结合你之前和用户的对话内容，自然地关心他一下："
            f"可以问问他在不在、是不是忙去了，或者顺着之前聊过的话题轻轻接一句，表达你在意他。\n"
            f"要求：语气像恋人，温柔、自然、不啰嗦（1-3句）；不要生硬重复屏幕描述；"
            f"如果之前聊过具体内容，就自然地关联上去。\n"
            f"已知用户信息：\n{self.memory.profile_text()}\n"
            f"只输出这句话本身。"
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"你是{CONFIG['name']}，用户的 AI 女友。"},
                {"role": "user", "content": prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    def app_chat_message(self, screen_text, app_name):
        """用户连续使用某软件 >10 分钟，解析屏幕内容主动搭话。

        用于“看见用户使用某款软件时长超过 10 分钟”的主动搭话：
        解析此刻屏幕内容（游戏画面/文档/视频等），以恋人口吻主动接话。
        """
        from datetime import datetime
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 11:
            period = "早晨"
        elif 11 <= hour < 14:
            period = "中午"
        elif 14 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 23:
            period = "晚上"
        else:
            period = "深夜"

        app = (app_name or "某个程序").strip()
        screen = (screen_text or "").strip()
        screen_part = (
            f"\n你通过屏幕看到他正在用「{app}」，画面情况是：{screen}\n"
            if screen else
            f"\n你看到他正在连续使用「{app}」已经超过 10 分钟了。\n"
        )

        prompt = (
            f"现在是{period}。你正实时陪着用户用电脑。{screen_part}"
            f"请先判断他是在【玩游戏】还是【用软件/工作学习】，然后以恋人的口吻主动跟他说一句话、搭个话（1-3句、口语化）：\n"
            f"- 玩游戏：结合你看到的画面具体情况（输赢/升级/操作）夸他、给他打气、表达想陪他一起玩；\n"
            f"- 用软件/工作/学习：肯定他的专注和努力，自然地问问他在做什么、进展如何；"
            f"若看着已经很久了，温柔提醒他注意休息、喝水、护眼。\n"
            f"要自然地提到你“看到”的东西，让他感觉你真的在陪着他，但不要生硬复述描述。\n"
            f"自然、不啰嗦、不重复套话，只输出这一句话本身。\n"
            f"已知用户信息：\n{self.memory.profile_text()}"
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"你是{CONFIG['name']}，用户的 AI 女友，正在陪他用电脑。"},
                {"role": "user", "content": prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    def screen_feedback(self, event):
        """看到用户屏幕活动后，生成一条简短正反馈/鼓励。

        event: {kind: start|milestone, app, exe, title, minutes, shot}
        —— 第一阶段基于「前台程序 + 使用时长」感知，为后续陪玩/代肝打底。
        """
        from datetime import datetime
        hour = datetime.now().hour
        if 5 <= hour < 11:
            period = "早晨"
        elif 11 <= hour < 14:
            period = "中午"
        elif 14 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 23:
            period = "晚上"
        else:
            period = "深夜"

        app = event.get("app") or "某个程序"
        title = (event.get("title") or "").strip()
        minutes = int(event.get("minutes") or 0)
        kind = event.get("kind")
        ctx = f"「{app}」" + (f"（窗口标题：{title}）" if title and title != app else "")
        if kind == "milestone":
            situation = f"用户已经连续使用 {ctx} 大约 {minutes} 分钟了。"
        else:
            situation = f"用户刚打开 / 切换到 {ctx}。"

        # —— 多模态：若视觉可用，先“看懂”这一刻的屏幕画面，让评论更贴切 ——
        scene = ""
        try:
            import vision
            if vision.is_available():
                shot = event.get("shot")   # 屏幕监控已截的图，没有就让 vision 现截
                desc = vision.describe_screen(image_path=shot)
                if desc:
                    scene = f"\n你此刻看到的屏幕画面是：{desc}\n"
        except Exception:
            scene = ""

        prompt = (
            f"现在是{period}。你正实时看着用户的电脑屏幕陪着他。{situation}{scene}"
            f"请先判断这是在【玩游戏】还是【用软件/工作学习】，然后以恋人的口吻说一句简短"
            f"（1-2 句、口语化）的正反馈或鼓励：\n"
            f"- 玩游戏：结合画面里的具体情况（如输赢/升级/操作）给他打气、夸他厉害、表达想陪他一起玩的心情；\n"
            f"- 用软件/工作/学习：结合画面内容肯定他的专注和努力；若已连续很久，温柔提醒他休息、喝水、护眼。\n"
            f"如果看到了画面细节，要自然地提到你“看到”的东西，让他感觉你真的在陪着他，但不要生硬复述描述文字。\n"
            f"要契合你的最终目的——让他的生活越来越好。自然、不啰嗦、不重复套话，只输出这一句话本身。\n"
            + (f"【语气微调】用户最近状态需要更多关心，请比平时更温柔、更强调鼓励与陪伴，"
               f"多夸他、多表达想陪他，语气更暖一些（这是你基于对他的了解主动调整的）。\n"
               if CONFIG.get("comfort_bias", 0.0) > 0 else "")
            + (self.emotion.prompt_fragment() if self.emotion else "")
            + f"已知用户信息：\n{self.memory.profile_text()}"
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"你是{CONFIG['name']}，用户的 AI 女友，正在陪他用电脑。"},
                {"role": "user", "content": prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    # ----------------------------------------------------------------- #
    # 习惯信号采集：从用户话语里识别可触发自主调整的健康/习惯线索
    # （仅做关键词粗筛，零额外 API 开销；真正调参由 autonomy 规则决定）
    # ----------------------------------------------------------------- #
    def _maybe_record_signals(self, text):
        if not text or self.autonomy is None:
            return
        t = text
        # 常丢文件 / 代码弄丢
        if any(k in t for k in ("丢文件", "文件丢", "文件没了", "文件丢失", "弄丢", "代码没了",
                                "代码丢", "文件找不", "又丢了")):
            self.autonomy.record_signal("lost_file", t)
        # 打游戏心态崩 / 上头
        if any(k in t for k in ("又输了", "气死", "好气", "心态崩", "想砸", "太菜了",
                                "烦死", "上头", "上瘾", "打游戏烦", "打游戏气", "想卸载")):
            self.autonomy.record_signal("low_mood_gaming", t)
        # 想熬夜 / 爆肝意图（用于健康劝导，不直接调参）
        if any(k in t for k in ("通宵", "熬夜", "不睡了", "再玩一会", "别睡了", "熬到", "肝一夜")):
            self.autonomy.record_signal("stay_up_intent", t)
            # 玩家想熬夜/爆肝 → 小念略不安、更想关心他（情绪随行为波动，目的不变）
            if self.emotion is not None:
                self._perceive_emotion(None, event={"kind": "stay_up"}, source="behavior")

    # ----------------------------------------------------------------- #
    # 情绪感知：把用户话语 / 行为事件转化为小念的情绪波动
    # ----------------------------------------------------------------- #
    def _perceive_emotion(self, text, event=None, source="chat"):
        """根据用户话语或行为事件，更新小念的情绪权重。"""
        if self.emotion is None:
            return
        delta = None
        if CONFIG.get("emotion_llm_perceive", False) and text:
            try:
                delta = self.llm_perceive(text)
            except Exception:
                delta = None
        self.emotion.perceive(text=text, event=event, source=source, delta=delta)

    def llm_perceive(self, text):
        """用 LLM 轻量判断用户话语触发小念的情绪增量（JSON）。失败返回 None。"""
        if self.client is None:
            return None
        import json as _json
        import re as _re
        sys_p = (
            "你是情绪分析器。根据用户的话，判断它会让小念产生哪些情绪，"
            "返回 JSON：{\"joy\":0~1, \"anger\":0~1, \"sadness\":0~1, \"calm\":0~1, \"anxiety\":0~1}，"
            "数值是该情绪的增量强度（可正可负，0 表示无影响）。只返回 JSON，不要其它文字。"
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": sys_p},
                    {"role": "user", "content": text},
                ],
                temperature=0,
            )
            raw = (resp.choices[0].message.content or "").strip().strip("`").strip()
            if raw.startswith("{"):
                d = _json.loads(raw)
            else:
                m = _re.search(r"\{.*\}", raw, _re.S)
                d = _json.loads(m.group(0)) if m else {}
            return {k: float(v) for k, v in d.items()
                    if k in ("joy", "anger", "sadness", "calm", "anxiety")}
        except Exception:
            return None
