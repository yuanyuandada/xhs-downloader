"""从粘贴文本里提取小红书笔记链接。

支持：
  - App「复制链接」整段文本（前后带表情、文案都无所谓，自动提取所有网址）
  - www.xiaohongshu.com/explore/{id}?xsec_token=...&xsec_source=...
  - www.xiaohongshu.com/discovery/item/{id}?...
  - www.xiaohongshu.com/user/profile/... （暂不支持，明确提示）
  - 短链 xhslink.com / xhslink.cn（跟随跳转还原真实地址）
  - 一次粘多条：逐条提取，去重
"""
import re
import time
from urllib.parse import urlparse

from curl_cffi import requests as creq

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}

URL_RE = re.compile(r"https?://[^\s\"'<>）】」]+", re.I)
BARE_XHS_RE = re.compile(
    r"(?:www\.)?(?:xiaohongshu\.com|rednote\.com|xhslink\.com|xhslink\.cn)/\S+", re.I
)
EXPLORE_RE = re.compile(
    r"(?:xiaohongshu\.com|rednote\.com)/(?:explore|discovery/item)/([0-9a-fA-F]{16,32})",
    re.I,
)


def extract_links(text):
    """返回去重后的笔记链接列表；解析不出时抛 ValueError。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("请先粘贴分享链接")

    raw = URL_RE.findall(text) or BARE_XHS_RE.findall(text)
    if not raw:
        raise ValueError("没找到链接。请在小红书 App 里点「分享 → 复制链接」，把整段文字粘贴进来")

    urls, seen = [], set()
    for u in raw:
        if not u.lower().startswith("http"):
            u = "https://" + u
        host = urlparse(u).netloc.lower()
        if (
            "xiaohongshu.com" in host
            or "rednote.com" in host
            or "xhslink.com" in host
            or "xhslink.cn" in host
        ):
            if "xhslink." in host:
                u = _resolve_short_link(u)
            key = u.split("#")[0]
            if key not in seen:
                seen.add(key)
                urls.append(u)

    notes = []
    seen_ids = set()
    for u in urls:
        m = EXPLORE_RE.search(u)
        if not m:
            continue
        if m.group(1) in seen_ids:
            continue
        seen_ids.add(m.group(1))
        notes.append(_normalize(u, m.group(1)))

    if not notes:
        if any("user/profile" in u for u in urls):
            raise ValueError("这是博主主页链接，本版本暂不支持整个博主下载；请打开具体笔记后分享链接")
        raise ValueError("没认出笔记链接。请在小红书 App 里打开那篇笔记，点「分享 → 复制链接」再粘贴")
    return notes


def _normalize(url, note_id):
    """统一成 https://www.xiaohongshu.com/explore/{id}?原始参数 形式。"""
    parsed = urlparse(url)
    query = ("?" + parsed.query) if parsed.query else ""
    page_url = f"https://www.xiaohongshu.com/explore/{note_id}{query}"
    return {"note_id": note_id, "url": page_url}


def _resolve_short_link(url):
    """xhslink 短链：跟随跳转还原真实地址。

    短链节点握手偶发被重置（SSL_ERROR_SYSCALL），所以带重试，
    后几次换 TLS 指纹兜底；跳转链最多跟 5 跳，兜底解析页面内跳转。
    """
    attempts = [
        "chrome131", "chrome131", "chrome124", "safari17_0", None,
    ]
    for _ in range(5):
        resp = None
        last_exc = None
        for imp in attempts:
            try:
                resp = creq.get(
                    url, headers=UA_HEADERS, timeout=15,
                    allow_redirects=False, impersonate=imp,
                )
                break
            except Exception as exc:
                last_exc = exc
                time.sleep(0.8)
        if resp is None:
            raise ValueError(f"短链打开失败：{last_exc}") from last_exc
        location = resp.headers.get("Location", "")
        if location:
            if location.startswith("/"):
                # 相对跳转
                from urllib.parse import urljoin
                location = urljoin(url, location)
            if "xhslink." in location:
                url = location  # 短链套短链，继续跳
                continue
            return location
        # 没有 Location：可能是 200 落地页，找页面内的跳转链接
        final = str(resp.url or "")
        if "xiaohongshu.com" in final or "rednote.com" in final:
            return final
        m = re.search(r'(?:href|url|href)=["\']?(https?://[^"\'>\s]+)', resp.text, re.I)
        if m and "xhslink." not in m.group(1):
            return m.group(1)
        if m:
            url = m.group(1)
            continue
        break
    raise ValueError("短链没有跳转信息，可能已失效，请在 App 里重新复制一次")
