"""下载引擎：串行队列 + 条间间隔防风控、重试、按文件去重、进度上报。

目录组织（共识）：保存目录 / 每篇笔记一个子文件夹（标题命名）/
图片按序编号，实况图成对同名（01.jpg + 01.mov），视频存 视频.mp4，
内附 笔记文案.txt（标题/作者/时间/链接/正文）。
"""
import glob
import os
import random
import re
import threading
import time

from . import client
from .client import XhsError

NOTE_GAP = 3.0        # 篇与篇之间的间隔（防风控），上下浮动 0~1.5 秒
FILE_GAP = 0.6        # 同一篇内文件之间的间隔
RETRY_TIMES = 2
RETRY_DELAY = 2

ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')
TYPE_LABEL = {"video": "视频", "normal": "图文"}


def sanitize(name, max_len=50):
    name = ILLEGAL_CHARS.sub("_", str(name or "")).strip().strip(".")
    return name[:max_len] or "无标题笔记"


def sniff_ext(data):
    """按文件头判断真实类型，防止扩展名与内容不符。"""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"\x89PNG":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp":
        return "mov" if data[8:10] == b"qt" else "mp4"
    return ""


class DownloadManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._items = []
        self.phase = "idle"  # idle | running | done
        self.target_dir = ""
        self._used_folders = {}  # 文件夹名 -> note_id，同批标题去重

    # ---------- 对外 ----------
    def start(self, links, save_dir):
        with self._lock:
            if self.phase == "running":
                return False, "已有任务在进行中"
            self.target_dir = save_dir
            self._used_folders = {}
            self._items = [
                {
                    "note_id": ln["note_id"],
                    "url": ln["url"],
                    "display": f"笔记 {i}/{len(links)}",
                    "status": "pending",
                    "progress": 0,
                    "reason": "",
                    "folder": "",
                    "hint": "",
                }
                for i, ln in enumerate(links, start=1)
            ]
            self.phase = "running"
        threading.Thread(target=self._run_batch, daemon=True).start()
        return True, ""

    def snapshot(self):
        with self._lock:
            counts = {"pending": 0, "running": 0, "done": 0, "skip": 0, "failed": 0}
            items = []
            for it in self._items:
                counts[it["status"]] = counts.get(it["status"], 0) + 1
                items.append(dict(it))
            return {
                "phase": self.phase,
                "folder": self.target_dir,
                "counts": counts,
                "items": items,
            }

    def is_running(self):
        return self.phase == "running"

    # ---------- 内部 ----------
    def _set(self, item, **patch):
        with self._lock:
            item.update(patch)

    def _run_batch(self):
        items = list(self._items)
        for idx, item in enumerate(items):
            try:
                self._work(item)
            except Exception as exc:  # 意外兜底，不让线程带崩
                self._set(item, status="failed", reason=str(exc) or "未知错误")
            if idx < len(items) - 1 and item["status"] != "failed":
                time.sleep(NOTE_GAP + random.uniform(0, 1.5))
        with self._lock:
            self.phase = "done"

    def _work(self, item):
        self._set(item, status="running", reason="获取笔记信息…")
        if self._already_done(
            os.path.join(self.target_dir, self._folder_name(item)), item["url"]
        ):
            name = self._folder_name(item)
            self._set(
                item, status="skip", progress=100, folder=name, reason="已存在，跳过",
            )
            return

        try:
            note = self._retry(
                lambda: client.fetch_note(item["url"], item["note_id"])
            )
        except XhsError as exc:
            self._set(item, status="failed", reason=str(exc))
            return

        folder = os.path.join(self.target_dir, self._folder_name(item, note["title"]))
        os.makedirs(folder, exist_ok=True)
        self._set(item, folder=os.path.basename(folder))

        # 组任务清单：[(文件名, 主URL, 备URL)]
        jobs = []
        if note["type"] == "video" and note["video"]:
            jobs.append(("视频.mp4", note["video"]["url"], ""))
        else:
            for idx, img in enumerate(note["images"], start=1):
                jobs.append((f"{idx:02d}.jpg", img["auto_url"], img["ci_url"]))
                if img["live_url"]:
                    jobs.append((f"{idx:02d}.mov", img["live_url"], ""))

        new_count, failed = 0, []
        for seq, (name, url, fallback) in enumerate(jobs):
            final = os.path.join(folder, name)
            if os.path.exists(final) and os.path.getsize(final) > 0:
                continue
            try:
                self._download_file(final, url, fallback, item, seq, len(jobs))
                new_count += 1
            except Exception as exc:
                failed.append(f"{name}：{exc}")
            time.sleep(FILE_GAP)

        self._write_txt(folder, note, failed)
        hint = ""
        if (
            note.get("video")
            and note["video"].get("low")
            and not client.has_login_cookie()
        ):
            hint = "视频清晰度可能受限；想要原画可点「高级 → 登录救援」后重新下载"

        all_present = bool(jobs) and all(
            os.path.exists(os.path.join(folder, j[0])) for j in jobs
        )
        if failed and not all_present:
            status, reason = "failed", "；".join(failed)
        elif not jobs:
            status, reason = "failed", "这篇笔记没有可下载的内容"
        elif new_count:
            status, reason = "done", f"完成：{new_count} 个新文件"
        else:
            status, reason = "skip", "已存在，跳过"
        self._set(item, status=status, progress=100, reason=reason, hint=hint)

    # ---------- 文件夹与去重 ----------
    def _folder_name(self, item, title=None):
        base = sanitize(title)
        taken_by = self._used_folders.get(base)
        if taken_by and taken_by != item["note_id"]:
            seq = 2
            while self._used_folders.get(f"{base}({seq})") not in (None, item["note_id"]):
                seq += 1
            base = f"{base}({seq})"
        self._used_folders.setdefault(base, item["note_id"])
        return base

    @staticmethod
    def _already_done(folder, url):
        """文件夹里已有匹配链接的文案 txt → 视为下载过，省一次请求。"""
        txt = os.path.join(folder, "笔记文案.txt")
        try:
            with open(txt, "r", encoding="utf-8") as fh:
                return url in fh.read(4096)
        except OSError:
            return False

    # ---------- 单文件下载 ----------
    def _download_file(self, final_path, url, fallback, item, seq, total):
        data = b""
        for candidate in (url, fallback):
            if not candidate:
                continue
            try:
                data = self._retry(
                    lambda c=candidate: client.get_bytes(
                        c,
                        on_progress=lambda done, tot, s=seq: self._set(
                            item, progress=min(99, int((s + done / max(tot or 1, 1))) * 100 / max(total, 1))
                        ),
                    )
                )
            except Exception:
                data = b""
            if len(data) > 256:
                break
        if len(data) <= 256:
            raise RuntimeError("下载失败")
        ext = sniff_ext(data)
        if not ext:
            raise RuntimeError("内容不是有效的图片/视频")
        root = os.path.splitext(final_path)[0]
        with open(f"{root}.{ext}", "wb") as fh:
            fh.write(data)

    @staticmethod
    def _write_txt(folder, note, failed):
        lines = [
            f"链接：{note['page_url']}",
            f"标题：{note['title']}",
            f"作者：{note['author']}",
            f"发布时间：{note['publish'] or '未知'}",
            f"类型：{TYPE_LABEL.get(note['type'], note['type'])}",
            "",
            note["desc"] or "（无正文）",
        ]
        if failed:
            lines += ["", "以下文件下载失败："] + failed
        try:
            with open(os.path.join(folder, "笔记文案.txt"), "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass

    @staticmethod
    def _retry(fn, times=RETRY_TIMES, delay=RETRY_DELAY):
        last = None
        for attempt in range(times + 1):
            try:
                return fn()
            except Exception as exc:
                last = exc
                if attempt < times:
                    time.sleep(delay)
        raise last if last else RuntimeError("重试失败")
