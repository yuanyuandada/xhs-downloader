"""端到端测试：从 explore 页抓真实链接，走 DownloadManager 全流程。"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from curl_cffi import requests as creq

from xhs_dl import client
from xhs_dl.downloader import DownloadManager

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_out")


def pick_links(n_video=1, n_normal=1):
    r = creq.get(
        "https://www.xiaohongshu.com/explore",
        impersonate="chrome146",
        timeout=20,
        headers={"accept": "text/html", "accept-language": "zh-CN,zh;q=0.9"},
    )
    pairs = re.findall(r'/explore/([0-9a-f]{24})\?([^"\'\s<)]+)', r.text)
    seen, vids, norms = set(), [], []
    for nid, tok in pairs:
        if nid in seen:
            continue
        seen.add(nid)
        url = f"https://www.xiaohongshu.com/explore/{nid}?{tok}"
        try:
            note = client.fetch_note(url, nid)
        except Exception as exc:
            print("  跳过一篇（", str(exc)[:60], "）")
            continue
        if note["type"] == "video" and len(vids) < n_video:
            vids.append((url, nid))
        elif note["type"] == "normal" and len(norms) < n_normal and len(note["images"]) >= 3:
            norms.append((url, nid))
        if len(vids) >= n_video and len(norms) >= n_normal:
            break
    return [{"note_id": nid, "url": url} for url, nid in vids + norms]


def main():
    os.makedirs(OUT, exist_ok=True)
    links = pick_links()
    print("选中测试笔记：", len(links))
    mgr = DownloadManager()
    ok, msg = mgr.start(links, OUT)
    assert ok, msg
    while mgr.is_running():
        time.sleep(1)
    snap = mgr.snapshot()
    print(json.dumps(snap["counts"], ensure_ascii=False))
    for it in snap["items"]:
        print(f"  [{it['status']}] {it['folder']} — {it['reason'][:80]}")
    # 展示产物
    for name in sorted(os.listdir(OUT)):
        path = os.path.join(OUT, name)
        if os.path.isdir(path):
            files = sorted(os.listdir(path))
            print("文件夹:", name)
            for f in files:
                print("   ", f, os.path.getsize(os.path.join(path, f)))
    # 再跑一遍验证去重
    mgr2 = DownloadManager()
    mgr2.start(links, OUT)
    while mgr2.is_running():
        time.sleep(1)
    print("第二轮（去重）:", json.dumps(mgr2.snapshot()["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
