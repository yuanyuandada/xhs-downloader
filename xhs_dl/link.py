"""从粘贴文本里提取小红书笔记链接。

支持：
  - App「复制链接」整段文本（前后带表情、文案都无所谓，自动提取所有网址）
  - www.xiaohongshu.com/explore/{id}?xsec_token=...&xsec_source=...
  - www.xiaohongshu.com/discovery/item/{id}?...
  - www.xiaohongshu.com/user/profile/... （暂不支持，明确提示）
  - xhslink.com 短链（跟随一次跳转还原真实地址）
  - 一次粘多条：逐条提取，去重
"""
import re
from urllib.parse import urlparse

from curl_cffi import requests as creq

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}

URL_RE = re.compile(r"https?://[^\s\"'<>）】」]+", re.I)
BARE_XHS_RE = re.compile(r"(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/\S+", re.I)
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
        if "xiaohongshu.com" in host or "rednote.com" in host or "xhslink.com" in host:
            if "xhslink.com" in host:
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
    """xhslink 短链：跟随一次 30x 跳转拿真实地址。"""
    try:
        resp = creq.get(
            url, headers=UA_HEADERS, timeout=15,
            allow_redirects=False, impersonate="chrome131",
        )
    except Exception as exc:
        raise ValueError(f"短链打开失败：{exc}") from exc
    location = resp.headers.get("Location", "")
    if not location:
        # 有的短链直接 200 返回落地页
        final = str(resp.url or "")
        if "xiaohongshu.com" in final:
            return final
        raise ValueError("短链没有跳转信息，可能已失效")
    return location
