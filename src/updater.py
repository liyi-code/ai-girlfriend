"""
src/updater.py — 便携分享版「自动更新」（git-free，基于 GitHub）

设计红线（最重要：绝不能把软件搞坏）：
  * 只下载/覆盖「远程仓库里存在的文件」，绝不碰 .env / data/ / venv/ / models/
    / personal_backup_* / *.personal_bak_* 等用户与本地文件（这些本就不在仓库树里）。
  * 覆盖前先把旧文件备份到 .update_backup/<时间戳>/；新代码若编译校验失败，
    立即把备份还原回去，保证「重启仍可用」。
  * 任何网络/写盘异常都「中止更新并保留当前可用版本」，绝不让软件打不开。
  * 更新只落盘、不影响正在运行的进程（Python 已加载的模块在内存里，重启才生效）。
  * 不依赖 git：收包的人机器上通常没装 git，这里只用标准库联网拉文件。

可用环境变量（在 .env 里设）：
  AUTO_UPDATE_ENABLED : true/false（默认 true）
  UPDATE_REPO         : 仓库，默认 liyi-code/ai-girlfriend
  UPDATE_BRANCH       : 分支，默认 main
  UPDATE_MIRROR       : 镜像前缀，例如 https://ghproxy.com/ （留空=直连 GitHub，适合国内被墙时填）
  UPDATE_PROXY        : 显式 HTTP 代理，例如 http://127.0.0.1:10090 （留空=跟随系统）
"""
import os
import json
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REPO = os.getenv("UPDATE_REPO", "liyi-code/ai-girlfriend")
BRANCH = os.getenv("UPDATE_BRANCH", "main").strip() or "main"
MIRROR = os.getenv("UPDATE_MIRROR", "").strip()          # 例如 https://ghproxy.com/
PROXY = os.getenv("UPDATE_PROXY", "").strip()

MANIFEST_PATH = os.path.join(BASE_DIR, ".update_manifest.json")
BACKUP_ROOT = os.path.join(BASE_DIR, ".update_backup")
VENV = os.path.join(BASE_DIR, "venv")
REQ_PATH = os.path.join(BASE_DIR, "requirements.txt")

HTTP_TIMEOUT = 25

# 这些路径永远不在仓库树里（由 .gitignore 保证），这里再兜底拦一道，双保险。
# 注意：.update_manifest.json 是更新器自己维护的基线文件，绝不参与自更新。
_PROTECTED_PREFIXES = (".env", "data/", "venv/", "models/", ".update_backup/",
                       "personal_backup_", ".env.personal_bak_",
                       ".update_manifest.json")


def _is_protected(relpath):
    p = relpath.replace("\\", "/")
    for pre in _PROTECTED_PREFIXES:
        if p == pre or p.startswith(pre) or ("/" + pre) in p:
            return True
    return False


def _api_url():
    u = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
    return (MIRROR + u) if MIRROR else u


def _raw_url(path):
    u = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{path}"
    return (MIRROR + u) if MIRROR else u


def _http_get(url, binary=True, timeout=HTTP_TIMEOUT):
    last_err = None
    for _ in range(2):   # 简单重试一次，抗瞬时抖动
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "ai-girlfriend-updater", "Accept": "*/*"})
            handlers = []
            if PROXY:
                handlers.append(urllib.request.ProxyHandler(
                    {"http": PROXY, "https": PROXY}))
            opener = urllib.request.build_opener(*handlers)
            with opener.open(req, timeout=timeout) as r:
                data = r.read()
            return data if binary else data.decode("utf-8", "replace")
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    raise last_err or RuntimeError("网络请求失败")


def get_remote_tree():
    """返回 (commit_sha, {相对项目根的路径: blob_sha})。失败抛异常。"""
    txt = _http_get(_api_url(), binary=False)
    payload = json.loads(txt)
    commit = payload.get("sha", "")
    files = {}
    for item in payload.get("tree", []):
        if item.get("type") == "blob":
            path = item["path"]
            if not _is_protected(path):
                files[path] = item["sha"]
    return commit, files


def load_manifest():
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"commit": "", "files": {}}


def save_manifest(commit, files):
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"commit": commit, "files": files},
                  f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST_PATH)


def current_version():
    """给 UI 显示当前版本（manifest 记录的 commit 短哈希）。"""
    man = load_manifest()
    c = (man.get("commit") or "").strip()
    if len(c) >= 7:
        return c[:7]
    return "开发版/未知"


def _py_files_to_verify():
    out = []
    src_dir = os.path.join(BASE_DIR, "src")
    if os.path.isdir(src_dir):
        for root, _dirs, files in os.walk(src_dir):
            for fn in files:
                if fn.endswith(".py"):
                    out.append(os.path.join(root, fn))
    for fn in os.listdir(BASE_DIR):
        if fn.endswith(".py"):
            out.append(os.path.join(BASE_DIR, fn))
    return out


def _verify_compile():
    """最关键的安全闸：新代码必须全部能编译，否则回滚。"""
    import py_compile
    for p in _py_files_to_verify():
        try:
            py_compile.compile(p, doraise=True)
        except Exception as e:
            return False, f"{os.path.relpath(p, BASE_DIR)}: {e}"
    return True, ""


def _run_pip():
    """若 requirements.txt 变化，安装新依赖（安静执行）。返回 (ok, msg)。"""
    if not os.path.isfile(REQ_PATH):
        return True, "无 requirements.txt，跳过"
    py = os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt" \
        else os.path.join(VENV, "bin", "python")
    if not os.path.isfile(py):
        return True, "未找到 venv 解释器，跳过依赖安装"
    try:
        r = subprocess.run([py, "-m", "pip", "install", "-r", REQ_PATH, "-q"],
                           capture_output=True, text=True, timeout=420)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout or "pip 安装失败")[-400:]
        return True, "依赖已更新"
    except Exception as e:
        return False, str(e)[:300]


def _prune_backups():
    try:
        if not os.path.isdir(BACKUP_ROOT):
            return
        subs = sorted(os.listdir(BACKUP_ROOT))
        for old in subs[:-3]:   # 只保留最近 3 次备份
            shutil.rmtree(os.path.join(BACKUP_ROOT, old), ignore_errors=True)
    except Exception:
        pass


def check():
    """检查是否有更新。返回 (has_update, info)。异常时 has_update=False。"""
    try:
        commit, files = get_remote_tree()
        man = load_manifest()
        if commit and commit == man.get("commit"):
            return False, {"reason": "same_commit", "commit": commit}
        changed = [p for p, sha in files.items()
                   if man.get("files", {}).get(p) != sha]
        removed = [p for p in man.get("files", {}) if p not in files]
        if not changed and not removed:
            return False, {"reason": "no_change", "commit": commit}
        return True, {"commit": commit, "changed": changed,
                      "removed": removed, "count": len(changed) + len(removed)}
    except Exception:
        return False, {"reason": "error",
                       "err": traceback.format_exc()[-400:]}


def update(progress=None):
    """执行更新（下载+覆盖+依赖+编译校验+回滚）。返回 (ok, msg)。"""
    def log(s):
        if progress:
            try:
                progress(s)
            except Exception:
                pass

    backup_dir = None
    try:
        commit, files = get_remote_tree()
        man = load_manifest()
        old_files = man.get("files", {})
        changed = [p for p, sha in files.items() if old_files.get(p) != sha]
        removed = [p for p in old_files if p not in files]

        if not changed and not removed:
            if commit and commit != man.get("commit"):
                save_manifest(commit, files)
            return True, "已经是最新版本啦～"

        log(f"发现 {len(changed)} 个文件需更新、{len(removed)} 个需删除")
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(BACKUP_ROOT, ts)
        os.makedirs(backup_dir, exist_ok=True)

        # 1) 下载变更文件：备份旧文件 → 下载到临时 → 原子替换
        fatal = None
        for i, p in enumerate(changed):
            log(f"下载 ({i + 1}/{len(changed)}): {p}")
            dest = os.path.join(BASE_DIR, p)
            bak = os.path.join(backup_dir, p)
            try:
                if os.path.exists(dest):
                    os.makedirs(os.path.dirname(bak), exist_ok=True)
                    shutil.copy2(dest, bak)
                data = _http_get(_raw_url(p), binary=True, timeout=90)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                tmp = dest + ".upd_tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, dest)   # 同卷原子替换，避免半成品
            except Exception as e:
                fatal = f"更新文件失败：{p} -> {e}"
                break

        # 2) 删除远程已移除的文件（仅我们管理过的）
        if fatal is None:
            for p in removed:
                dest = os.path.join(BASE_DIR, p)
                if os.path.exists(dest):
                    try:
                        bak = os.path.join(backup_dir, p + ".delbak")
                        os.makedirs(os.path.dirname(bak), exist_ok=True)
                        shutil.copy2(dest, bak)
                        os.remove(dest)
                    except Exception:
                        pass

        # 3) 依赖安装（若 requirements 变化）
        if fatal is None and "requirements.txt" in changed:
            log("正在安装/更新依赖…")
            ok, msg = _run_pip()
            if not ok:
                log("⚠ 依赖安装失败：" + msg)

        # 4) 编译校验（最关键的安全闸）
        if fatal is None:
            log("校验新代码…")
            ok, err = _verify_compile()
            if not ok:
                fatal = "新代码校验失败：" + err

        # 5) 失败 → 回滚
        if fatal is not None:
            log("更新中止，正在回滚…")
            _restore_backup(backup_dir)
            return False, fatal + "（已自动回滚，当前版本仍可用）"

        # 6) 成功 → 写新 manifest
        save_manifest(commit, files)
        _prune_backups()
        return True, f"已更新到新版本（{len(changed)} 个文件）✨ 重启小念后生效"

    except Exception as e:
        if backup_dir and os.path.isdir(backup_dir):
            try:
                _restore_backup(backup_dir)
            except Exception:
                pass
        return False, f"更新出错已中止（不影响使用）：{e}"


def _restore_backup(backup_dir):
    for root, _dirs, names in os.walk(backup_dir):
        for name in names:
            src = os.path.join(root, name)
            rel = os.path.relpath(src, backup_dir)
            if rel.endswith(".delbak"):
                dest = os.path.join(BASE_DIR, rel[:-7])   # 还原被删除的文件
            else:
                dest = os.path.join(BASE_DIR, rel)         # 还原被覆盖的文件
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)
            except Exception:
                pass


def check_and_apply(progress=None):
    """检查并在有更新时自动应用。返回 (applied, msg)。"""
    try:
        has, info = check()
    except Exception as e:
        return False, f"检查更新失败（可能是网络/被墙，不影响使用）：{e}"
    if not has:
        if info.get("reason") == "error":
            return False, "检查更新失败（网络/被墙？不影响使用）"
        return False, "已经是最新版本～"
    ok, msg = update(progress)
    return ok, msg


def changelog():
    """拉取远程 CHANGELOG.md 内容（用于「查看更新日志」）。失败返回 None。"""
    try:
        return _http_get(_raw_url("CHANGELOG.md"), binary=False, timeout=20)
    except Exception:
        return None
