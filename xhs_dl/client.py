"""小红书客户端：游客身份维护 + 笔记页面获取 + 数据提取。

路线：不用签名 API，直接请求笔记网页（SSR），解析 window.__INITIAL_STATE__。
游客身份 = 首次访问首页收集平台下发的匿名 Cookie（a1 等），持久化复用；
用户若在「登录救援」里提供了 Cookie（扫码或手动粘贴），则叠加在其上。
"""
import json
import logging
import re
import threading
from datetime import datetime

import yaml
from curl_cffi import requests as creq

from . import settings

log = logging.getLogger("client")

IMPERSONATE = "chrome146"
HOME = "https://www.xiaohongshu.com"

INITIAL_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(.+?)</script>", re.S)
YAML_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
UNESCAPE_U_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


class XhsError(RuntimeError):
    """带用户可读信息的错误。kind: network/risk/login/gone/parse"""

    def __init__(self, message, kind="network"):
        super().__init__(message)
        self.kind = kind


def _unescape(url):
    """接口里的 URL 常带 \\u002F 转义，还原成正常网址。"""
    if not url:
        return ""
    url = url.replace("\\/", "/")
    return UNESCAPE_U_RE.sub(lambda m: chr(int(m.group(1), 16)), url)


def _deep_get(data, keys, default=None):
    cur = data
    try:
        for key in keys:
            cur = cur[key]
        return cur
    except (KeyError, IndexError, TypeError):
        return default


def _headers(referer=HOME):
    return {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "accept-language": "zh-CN,zh;q=0.9",
        "referer": referer,
    }


# ---------- Cookie 池：游客 Cookie + 救援登录 Cookie ----------

class CookiePool:
    def __init__(self):
        self._lock = threading.Lock()
        self.guest = self._load_json(settings.GUEST_JAR_PATH)
        self.login = self._parse_cookie_text(settings.load_cookie_text())

    @staticmethod
    def _load_json(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return {str(k): str(v) for k, v in data.items()}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _parse_cookie_text(text):
        out = {}
        for part in (text or "").replace("\n", ";").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k.strip():
                    out[k.strip()] = v.strip()
        return out

    @staticmethod
    def _save_json(path, data):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)

    def merged(self):
        with self._lock:
            out = dict(self.guest)
            out.update(self.login)
            return out

    def absorb_response(self, resp):
        """把响应下发的 Set-Cookie 并进游客池（a1/webId 等匿名身份）。"""
        try:
            fresh = resp.cookies.get_dict()
        except Exception:
            return
        if not fresh:
            return
        with self._lock:
            changed = False
            for k, v in fresh.items():
                if self.guest.get(k) != v:
                    self.guest[k] = v
                    changed = True
            if changed:
                try:
                    self._save_json(settings.GUEST_JAR_PATH, self.guest)
                except OSError:
                    pass

    def set_login_dict(self, cookies):
        with self._lock:
            self.login = {str(k): str(v) for k, v in cookies.items() if k and v}

    def has_login(self):
        with self._lock:
            return bool(self.login.get("web_session"))

    def clear_login(self):
        with self._lock:
            self.login = {}


POOL = CookiePool()


def has_login_cookie():
    return POOL.has_login()


def set_login_cookie_text(text):
    POOL.set_login_dict(POOL._parse_cookie_text(text))
    settings.save_cookie_text(text or "")


def clear_login_cookie():
    POOL.clear_login()
    settings.save_cookie_text("")


# ---------- 页面获取与解析 ----------

def _guest_warmup():
    """没有 a1 时先访问一次首页，收集平台下发的匿名 Cookie。"""
    if POOL.merged().get("a1"):
        return
    try:
        resp = creq.get(
            HOME, headers=_headers(), impersonate=IMPERSONATE,
            timeout=20, allow_redirects=True,
        )
        POOL.absorb_response(resp)
        log.info("游客 Cookie 收集完成：%s", sorted(POOL.merged())[:8])
    except Exception as exc:
        log.warning("首页预热失败（继续尝试直连笔记页）：%s", exc)


def fetch_note_page(url):
    """请求笔记页面，返回 HTML 文本。失败抛 XhsError。"""
    _guest_warmup()
    try:
        resp = creq.get(
            url,
            headers=_headers(),
            cookies=POOL.merged(),
            impersonate=IMPERSONATE,
            timeout=30,
            allow_redirects=True,
        )
    except Exception as exc:
        raise XhsError(f"网络请求失败：{exc}", "network") from exc
    POOL.absorb_response(resp)
    code = resp.status_code
    if code in (461, 406):
        raise XhsError(
            "被平台临时拦截（风控）。请过几分钟再试；反复出现的话，"
            "点「高级 → 登录救援」扫码后通常立刻恢复",
            "risk",
        )
    if code in (404, 410):
        raise XhsError("笔记不存在或已被删除", "gone")
    if code != 200:
        raise XhsError(f"页面返回异常状态 {code}", "network")
    return resp.text


def _extract_state(html):
    m = INITIAL_STATE_RE.search(html)
    if not m:
        return None
    text = YAML_ILLEGAL_RE.sub("", m.group(1))
    text = text.replace("new Map([])", "[]").replace("undefined", "null")
    try:
        return yaml.safe_load(text)
    except Exception as exc:
        log.warning("INITIAL_STATE 解析失败：%s", exc)
        return None


def _pick_note(state, note_id):
    if not isinstance(state, dict):
        return None
    detail = _deep_get(state, ["note", "noteDetailMap"], {}) or {}
    entry = detail.get(note_id) or next(iter(detail.values()), None)
    note = _deep_get(entry or {}, ["note"])
    if note:
        return note
    return _deep_get(state, ["noteData", "data", "noteData"]) or None


# ---------- 数据提取 ----------

def _image_token(url):
    """从图片 URL 提取文件 token：第 5 个 / 之后、! 之前的部分。"""
    if not url:
        return ""
    parts = str(url).split("/")
    token = "/".join(parts[5:]) if len(parts) > 5 else ""
    return token.split("!")[0]


def _pick_stream_url(stream):
    """从 stream 结构（按编码分组）里挑一个最优直链：h264 优先，再比码率。"""
    if not isinstance(stream, dict):
        return ""
    best = None
    for codec, items in stream.items():
        if not isinstance(items, list) or not items:
            continue
        item = items[0]
        if not isinstance(item, dict):
            continue
        url = _unescape(item.get("masterUrl") or "") or _unescape(
            (item.get("backupUrls") or [None])[0] or ""
        )
        if not url:
            continue
        score = (
            1 if str(codec).startswith("h264") else 0,
            int(item.get("videoBitrate") or 0),
            int(item.get("height") or 0),
        )
        if best is None or score > best[0]:
            best = (score, url)
    return best[1] if best else ""


def _live_video_url(item):
    """实况图短视频：三代字段位置逐一兜底。"""
    url = _pick_stream_url(_deep_get(item, ["livePhoto", "media", "stream"]))
    if url:
        return url
    url = _pick_stream_url(item.get("stream") if isinstance(item, dict) else None)
    if url:
        return url
    for key in ("livePhotoVideo", "liveUrl"):
        raw = item.get(key) if isinstance(item, dict) else None
        if isinstance(raw, str) and raw:
            url = _unescape(raw)
            if url.startswith("http"):
                return url
    return ""


def _video_info(note):
    video = note.get("video") or {}
    # 直链原图：originVideoKey 无需走 stream
    key = _deep_get(video, ["consumer", "originVideoKey"]) or ""
    if key:
        return {"url": f"https://sns-video-bd.xhscdn.com/{key}", "height": 0, "low": False}
    stream = _deep_get(video, ["media", "stream"]) or {}
    candidates = []
    for codec, items in stream.items():
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            url = _unescape(it.get("masterUrl") or "") or _unescape(
                (it.get("backupUrls") or [None])[0] or ""
            )
            if url:
                candidates.append(
                    {
                        "url": url,
                        "height": int(it.get("height") or 0),
                        "bitrate": int(it.get("videoBitrate") or 0),
                        "h264": 1 if str(codec).startswith("h264") else 0,
                    }
                )
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["height"], c["bitrate"], c["h264"]))
    best = candidates[-1]
    # 游客态常见：最高只有一档且不到 1080p → 提示可登录救援
    low = best["height"] < 1080
    return {"url": best["url"], "height": best["height"], "low": low}


def extract_note(url, note_id, html):
    """从页面 HTML 提取结构化笔记数据。"""
    state = _extract_state(html)
    note = _pick_note(state, note_id) if state else None
    if not note:
        if "验证" in html or "captcha" in html.lower():
            raise XhsError(
                "触发了平台人机验证，请过几分钟再试；反复出现请用「登录救援」",
                "risk",
            )
        raise XhsError(
            "没拿到笔记数据。若这篇笔记设置了可见范围（仅自己/仅粉丝），"
            "需要「高级 → 登录救援」后才能下载",
            "login",
        )

    if str(note.get("onlyOwnerSee") or "").lower() == "true":
        raise XhsError("这篇笔记仅作者自己可见，无法下载", "login")

    title = str(note.get("title") or "").strip()
    desc = str(note.get("desc") or "").strip()
    author = (
        _deep_get(note, ["user", "nickname"])
        or _deep_get(note, ["user", "nickName"])
        or "未知作者"
    )
    ts = note.get("time")
    publish = (
        datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
        if isinstance(ts, (int, float)) and ts > 0
        else ""
    )

    images = []
    for item in note.get("imageList") or []:
        if not isinstance(item, dict):
            continue
        token = _image_token(item.get("urlDefault") or item.get("url") or "")
        if not token:
            continue
        images.append(
            {
                "token": token,
                "auto_url": f"https://sns-img-bd.xhscdn.com/{token}",
                "ci_url": f"https://ci.xiaohongshu.com/{token}?imageView2/format/png",
                "live_url": _live_video_url(item),
            }
        )

    video = _video_info(note) if str(note.get("type") or "") == "video" else None

    return {
        "note_id": note_id,
        "page_url": url,
        "type": "video" if video else "normal",
        "title": title or "无标题笔记",
        "desc": desc,
        "author": author,
        "publish": publish,
        "images": images,
        "video": video,
    }


def thumb_url(token):
    """预览缩略图（480 宽 jpg，约几十 KB，避免直接加载原图）。"""
    return f"https://ci.xiaohongshu.com/{token}?imageView2/2/w/480/format/jpg"


def fetch_note(url, note_id):
    """完整流程：取页面 → 提取。"""
    html = fetch_note_page(url)
    return extract_note(url, note_id, html)


# ---------- 文件下载 ----------

def get_bytes(url, on_progress=None):
    """下载一个文件的全部字节；on_progress(done, total) 汇报进度。"""
    resp = creq.get(
        url,
        headers=_headers(),
        impersonate=IMPERSONATE,
        timeout=(15, 120),
        stream=True,
    )
    try:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        buf = bytearray()
        for chunk in resp.iter_content(256 * 1024):
            if chunk:
                buf.extend(chunk)
                if on_progress:
                    on_progress(len(buf), total)
        if total and len(buf) < total:
            raise XhsError("下载不完整", "network")
        return bytes(buf)
    finally:
        resp.close()
