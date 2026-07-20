import json
import os
from datetime import datetime
from config import CONFIG


class Memory:
    """长期记忆：记住关于用户的信息、小事，以及最近的对话。"""

    def __init__(self, path=None):
        self.path = path or os.path.join(CONFIG["data_dir"], "memory.json")
        self.data = {"profile": {}, "facts": [], "history": []}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                pass
        self.data.setdefault("profile", {})
        self.data.setdefault("facts", [])
        self.data.setdefault("history", [])

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def remember_fact(self, fact):
        fact = fact.strip()
        if fact and fact not in self.data["facts"]:
            self.data["facts"].append(fact)
            self.save()

    def set_profile(self, key, value):
        self.data["profile"][key] = value
        self.save()

    def add_message(self, role, content):
        self.data["history"].append({
            "role": role,
            "content": content,
            "time": datetime.now().isoformat(timespec="seconds"),
        })
        if len(self.data["history"]) > 200:
            self.data["history"] = self.data["history"][-200:]
        self.save()

    def recent_history(self, n=20):
        return self.data["history"][-n:]

    def profile_text(self):
        lines = []
        if self.data["profile"]:
            lines.append("【关于你的信息】")
            for k, v in self.data["profile"].items():
                lines.append(f"- {k}: {v}")
        if self.data["facts"]:
            lines.append("【我记住的小事】")
            for f_ in self.data["facts"][-20:]:
                lines.append(f"- {f_}")
        return "\n".join(lines) if lines else "（我还不太了解你，慢慢告诉我吧～）"
