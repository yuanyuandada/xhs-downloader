"""应用数据目录与设置。

结构沿用网易云下载器：数据优先放 exe 旁边（data/），不可写时退回 %APPDATA%。
下载目录默认 exe 旁边的 download/，界面里可改。
"""
import json
import os
import sys

APP_NAME = "XiaohongshuDownloader"


def _init_dirs():
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(exe_dir, "data")
    try:
        os.makedirs(data_dir, exist_ok=True)
        probe = os.path.join(data_dir, ".probe")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
    except OSError:
        data_dir = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME
        )
        os.makedirs(data_dir, exist_ok=True)
    return exe_dir, data_dir


EXE_DIR, DATA_DIR = _init_dirs()
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
COOKIE_PATH = os.path.join(DATA_DIR, "cookie.txt")
GUEST_JAR_PATH = os.path.join(DATA_DIR, "guest_cookies.json")
LOG_PATH = os.path.join(DATA_DIR, "app.log")
DEFAULT_SAVE_DIR = os.path.join(EXE_DIR, "download")

DEFAULTS = {"save_dir": DEFAULT_SAVE_DIR}


def load_settings():
    merged = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            merged.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return merged


def save_settings(patch):
    current = load_settings()
    current.update({k: v for k, v in patch.items() if v is not None})
    with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False, indent=2)
    return current


def load_cookie_text():
    try:
        with open(COOKIE_PATH, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def save_cookie_text(text):
    with open(COOKIE_PATH, "w", encoding="utf-8") as fh:
        fh.write(text or "")
