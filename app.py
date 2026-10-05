"""小红书下载器 — 桌面入口。

GUI 模式：python app.py            （pywebview + WebView2 窗口）
调试模式：python app.py --web 8766 （浏览器打开 http://127.0.0.1:8766，便于开发测试）
"""
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from xhs_dl import client, settings as st
from xhs_dl.client import XhsError
from xhs_dl.downloader import DownloadManager
from xhs_dl.link import extract_links

log = logging.getLogger("app")

DISCLAIMER_VERSION = 1
DISCLAIMER_TEXT = """1. 本软件为免费的个人自用工具，按“现状”提供。开发者不对可用性、稳定性作任何保证；小红书平台改版或风控策略变化可能导致部分功能失效。
2. 本软件与小红书官方没有任何隶属或合作关系。内容数据均来自平台公开页面，版权归原创作者所有。
3. 通过本软件下载的内容仅供个人收藏、学习使用。严禁用于商业用途、二次发布、冒充原创或其他侵犯他人合法权益的行为，由此产生的一切责任由使用者本人承担。
4. 请遵守《小红书用户协议》及相关法律法规，不得利用本软件进行批量抓取、绕过平台限制或其他滥用行为。
5. 使用本软件即表示你已阅读并同意以上全部内容。"""


def _setup_logging():
    handler = logging.FileHandler(st.LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def _web_dir():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "web")


class Api:
    """前后端桥：所有方法返回 dict，绝不抛异常（ok=False 时带 error）。"""

    def __init__(self, web_mode=False):
        self.web_mode = web_mode
        self.manager = DownloadManager()
        self._login_watching = False

    # ---------- 设置 ----------
    def get_settings(self):
        s = st.load_settings()
        return {
            "ok": True,
            "save_dir": s["save_dir"],
            "logged_in": client.has_login_cookie(),
            "identity": "已登录救援身份" if client.has_login_cookie() else "游客身份（免登录）",
            "web_mode": self.web_mode,
            "data_dir": st.DATA_DIR,
            "disclaimer_agreed": bool(
                s.get("disclaimer_agreed")
                and s.get("disclaimer_version") == DISCLAIMER_VERSION
            ),
            "disclaimer_text": DISCLAIMER_TEXT,
        }

    def agree_disclaimer(self):
        st.save_settings(
            {"disclaimer_agreed": True, "disclaimer_version": DISCLAIMER_VERSION}
        )
        return {"ok": True}

    def exit_app(self):
        if self.web_mode:
            return {"ok": True, "closed": False}
        import webview

        try:
            webview.windows[0].destroy()
        except Exception:
            pass
        return {"ok": True, "closed": True}

    def set_settings(self, save_dir=None):
        try:
            if save_dir:
                os.makedirs(save_dir, exist_ok=True)
            st.save_settings({"save_dir": save_dir})
            return self.get_settings()
        except OSError as exc:
            return {"ok": False, "error": f"保存设置失败：{exc}"}

    def choose_folder(self):
        if self.web_mode:
            return {"ok": False, "error": "网页调试模式不支持选文件夹，请手动输入路径"}
        import webview

        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            return self.set_settings(save_dir=result[0])
        return {"ok": True, "path": None}

    def open_folder(self):
        try:
            s = st.load_settings()
            os.makedirs(s["save_dir"], exist_ok=True)
            os.startfile(s["save_dir"])  # noqa: S606 Windows 资源管理器
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    # ---------- 解析预览 ----------
    def preview_links(self, text):
        """解析粘贴的链接，返回每篇笔记的预览信息（不下载）。"""
        if self.manager.is_running():
            return {"ok": False, "error": "已有任务在进行中，等它跑完"}
        try:
            links = extract_links(text)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        items = []
        for i, ln in enumerate(links):
            try:
                note = client.fetch_note(ln["url"], ln["note_id"])
                live = sum(1 for im in note["images"] if im["live_url"])
                cover = note["images"][0]["token"] if note["images"] else ""
                items.append(
                    {
                        "note_id": ln["note_id"],
                        "url": ln["url"],
                        "ok": True,
                        "title": note["title"],
                        "author": note["author"],
                        "publish": note["publish"],
                        "type": note["type"],
                        "count": 1 if note["video"] else len(note["images"]),
                        "live": live,
                        "cover_token": cover,
                    }
                )
            except XhsError as exc:
                items.append(
                    {"note_id": ln["note_id"], "url": ln["url"], "ok": False,
                     "error": str(exc)}
                )
            if i < len(links) - 1:
                time.sleep(1.0)  # 解析间隔，防风控
        return {"ok": True, "items": items}

    # ---------- 下载 ----------
    def start_selected(self, links):
        if self.manager.is_running():
            return {"ok": False, "error": "已有任务在进行中，等它跑完"}
        clean = []
        for ln in links or []:
            if not isinstance(ln, dict):
                continue
            nid, url = str(ln.get("note_id") or ""), str(ln.get("url") or "")
            if nid and url:
                clean.append({"note_id": nid, "url": url})
        if not clean:
            return {"ok": False, "error": "没有勾选任何笔记"}
        s = st.load_settings()
        save_dir = s["save_dir"]
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"保存目录不可用：{exc}"}
        ok, msg = self.manager.start(clean, save_dir)
        if not ok:
            return {"ok": False, "error": msg}
        return {"ok": True, "count": len(clean)}

    def open_url(self, url):
        url = str(url or "")
        if not url.startswith(("https://www.xiaohongshu.com", "https://www.rednote.com")):
            return {"ok": False, "error": "只支持打开小红书链接"}
        try:
            os.startfile(url)  # noqa: S606 系统默认浏览器
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def start_download(self, text, save_dir=None):
        if self.manager.is_running():
            return {"ok": False, "error": "已有任务在进行中，等它跑完"}
        try:
            links = extract_links(text)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if save_dir:
            st.save_settings({"save_dir": save_dir})
        else:
            save_dir = st.load_settings()["save_dir"]
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"保存目录不可用：{exc}"}
        ok, msg = self.manager.start(links, save_dir)
        if not ok:
            return {"ok": False, "error": msg}
        return {"ok": True, "count": len(links)}

    def poll_status(self):
        return {"ok": True, **self.manager.snapshot()}

    # ---------- 登录救援 ----------
    def login_state(self):
        return {"ok": True, "logged_in": client.has_login_cookie()}

    def open_login_window(self):
        """弹出小红书官方登录页，登录成功后自动抓取 Cookie（仅桌面模式）。"""
        if self.web_mode:
            return {"ok": False, "error": "调试模式请在网页版小红书登录后手动粘贴 Cookie"}
        if self._login_watching:
            return {"ok": True, "started": True}
        import webview

        win = webview.create_window(
            "登录小红书 — 登录完成后本窗口会自动关闭",
            "https://www.xiaohongshu.com",
            width=430,
            height=760,
            on_top=True,
        )
        self._login_watching = True

        def watch():
            ok = False
            for _ in range(150):  # 最多等 5 分钟
                time.sleep(2)
                try:
                    raw = win.get_cookies() or []
                except Exception:
                    continue
                jar = {}
                for c in raw:
                    if isinstance(c, dict):
                        name, value = c.get("name"), c.get("value")
                    else:
                        name, value = getattr(c, "name", None), getattr(c, "value", None)
                    if name and value:
                        jar[name] = value
                if jar.get("web_session"):
                    client.set_login_cookie_text(
                        "; ".join(f"{k}={v}" for k, v in jar.items())
                    )
                    ok = True
                    log.info("救援登录成功，Cookie 键：%s", sorted(jar))
                    break
            self._login_watching = False
            try:
                win.destroy()
            except Exception:
                pass
            log.info("登录救援窗口结束，成功=%s", ok)

        threading.Thread(target=watch, daemon=True).start()
        return {"ok": True, "started": True}

    def save_cookie_text(self, text):
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "请先粘贴 Cookie 内容"}
        if "=" not in text or len(text) < 30:
            return {"ok": False, "error": "这不像有效的 Cookie，请确认复制的是完整一行"}
        client.set_login_cookie_text(text)
        return {"ok": True, **self.login_state()}

    def clear_cookie(self):
        client.clear_login_cookie()
        return {"ok": True, **self.login_state()}


# ---------- 网页调试模式 ----------
def run_web(port):
    api = Api(web_mode=True)
    web_dir = _web_dir()
    mime = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            name = "index.html" if self.path == "/" else self.path.lstrip("/").split("?")[0]
            path = os.path.join(web_dir, name)
            if not os.path.isfile(path):
                self._send(404, b"not found", "text/plain")
                return
            ext = os.path.splitext(path)[1].lower()
            with open(path, "rb") as fh:
                self._send(200, fh.read(), mime.get(ext, "application/octet-stream"))

        def do_POST(self):
            if not self.path.startswith("/api/"):
                self._send(404, b"not found", "text/plain")
                return
            name = self.path[len("/api/"):]
            method = getattr(api, name, None)
            if method is None:
                self._send(404, b"no such api", "text/plain")
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"[]"
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("gbk", "replace")  # 兼容命令行工具发的本地编码
            try:
                args = json.loads(text or "[]")
                result = method(*args) if isinstance(args, list) else method(**args)
            except Exception as exc:
                log.error("api %s failed", name, exc_info=True)
                result = {"ok": False, "error": f"内部错误：{exc}"}
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"调试模式已启动：http://127.0.0.1:{port}")
    server.serve_forever()


# ---------- 桌面模式 ----------
def run_gui():
    import webview

    api = Api(web_mode=False)
    webview.create_window(
        "小红书下载器",
        os.path.join(_web_dir(), "index.html"),
        js_api=api,
        width=960,
        height=720,
        min_size=(760, 560),
        background_color="#12141a",
    )
    webview.start()


if __name__ == "__main__":
    _setup_logging()
    if "--web" in sys.argv:
        idx = sys.argv.index("--web")
        port = int(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 else 8766
        run_web(port)
    else:
        run_gui()
