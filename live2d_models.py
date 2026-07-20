"""Live2D 模型自定义系统：模型发现 + 元数据注册表（来源/授权/可否商用）。

gui.py 与 live2d_app.py 共用，让任意 Live2D 模型（含未来提供的「可商用」模型）
都能被一键发现、切换、管理，并记录其授权信息，避免参赛时误用未授权模型。
"""

import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(BASE_DIR, "assets", "live2d")
REGISTRY_PATH = os.path.join(ASSET_DIR, "models.json")


def model_display(rel):
    name = os.path.basename(rel)
    for ext in (".model3.json", ".model.json", ".json"):
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    return name


def discover_models():
    """扫描 assets/live2d 下所有 Cubism 模型，返回相对项目根的路径列表。"""
    found = []
    if os.path.isdir(ASSET_DIR):
        for root, _, files in os.walk(ASSET_DIR):
            for f in files:
                low = f.lower()
                if low.endswith(".model3.json"):
                    ap = os.path.abspath(os.path.join(root, f))
                    found.append(os.path.relpath(ap, BASE_DIR).replace(os.sep, "/"))
                elif low.endswith(".json") and low != "model3.json":
                    base = os.path.splitext(f)[0]
                    if os.path.exists(os.path.join(root, base + ".moc")) or \
                       os.path.exists(os.path.join(root, base + ".moc3")):
                        ap = os.path.abspath(os.path.join(root, f))
                        found.append(os.path.relpath(ap, BASE_DIR).replace(os.sep, "/"))
    seen, uniq = set(), []
    for rel in found:
        if rel not in seen:
            seen.add(rel)
            uniq.append(rel)
    return uniq


def load_registry():
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_registry(reg):
    try:
        os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def upsert_model_meta(rel, **meta):
    reg = load_registry()
    entry = dict(reg.get(rel, {}))
    entry.update(meta)
    entry["rel"] = rel
    reg[rel] = entry
    save_registry(reg)
    return entry


def remove_model_meta(rel):
    reg = load_registry()
    if rel in reg:
        del reg[rel]
        save_registry(reg)


def list_models_with_meta():
    """返回 [(显示名, 相对路径, 元数据)]，元数据含 source/license/commercial/removable。"""
    rels = discover_models()
    reg = load_registry()
    out = []
    for rel in rels:
        meta = dict(reg.get(rel, {}))
        meta.setdefault("source", "未知")
        meta.setdefault("license", "未知（请确认授权）")
        meta.setdefault("commercial", False)
        meta.setdefault("removable", False)
        out.append((model_display(rel), rel, meta))
    return out
