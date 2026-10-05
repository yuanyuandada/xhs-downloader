/* 小红书下载器 - 前端逻辑（pywebview 与网页调试模式通用） */
"use strict";

const $ = (sel) => document.querySelector(sel);

const state = {
  bridge: null,
  settings: null,
  previews: [],
  pollTimer: null,
  loginTimer: null,
  running: false,
};

/* ---------- 桥 ---------- */
const httpBridge = {
  call: (name, ...args) =>
    fetch("/api/" + name, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }).then((r) => r.json()),
};

const pyBridge = {
  call: (name, ...args) => window.pywebview.api[name](...args),
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function detectBridge() {
  const t0 = Date.now();
  while (Date.now() - t0 < 2500) {
    if (window.pywebview && window.pywebview.api) return pyBridge;
    await sleep(60);
  }
  return httpBridge;
}

let bridgePromise = null;
function ensureBridge() {
  if (!bridgePromise) {
    bridgePromise = detectBridge().then((b) => {
      state.bridge = b;
      return b;
    });
  }
  return bridgePromise;
}

async function apiCall(name, ...args) {
  try {
    const bridge = await ensureBridge();
    return await bridge.call(name, ...args);
  } catch (err) {
    return { ok: false, error: err && err.message ? err.message : String(err) };
  }
}

/* ---------- 基础 UI ---------- */
let toastTimer = null;
function toast(msg, kind = "") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast " + kind + " show";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = "toast"), 3200);
}

function applySettings(s) {
  state.settings = s;
  $("#saveDir").textContent = s.save_dir;
  $("#saveDir").title = s.save_dir;
  const badge = $("#identity");
  badge.textContent = s.identity;
  badge.className = "badge" + (s.logged_in ? " on" : "");
  if (s.web_mode) $("#btnLoginWindow").disabled = true;
  if (!s.disclaimer_agreed) showDisclaimer(true);
}

/* ---------- 免责声明 ---------- */
function showDisclaimer(consentMode) {
  const s = state.settings || {};
  $("#disclaimerBody").textContent = s.disclaimer_text || "";
  $("#disclaimerMask").hidden = false;
  $("#btnAgree").hidden = !consentMode;
  $("#btnDecline").hidden = !consentMode;
  $("#btnDisclaimerClose").hidden = consentMode;
  $("#disclaimerTitle").textContent = consentMode
    ? "使用前请阅读 · 免责声明"
    : "免责声明";
}

/* ---------- 解析预览 ---------- */
function typeTags(it) {
  const tags = [];
  if (it.type === "video") tags.push(["视频", ""]);
  else tags.push([`图文 · ${it.count} 图`, ""]);
  if (it.live > 0) tags.push([`实况 ×${it.live}`, "live"]);
  return tags;
}

function coverCell(it) {
  if (!it.cover_token) {
    const d = document.createElement("div");
    d.className = "cover-missing";
    d.textContent = it.type === "video" ? "🎬" : "🖼️";
    return d;
  }
  const img = document.createElement("img");
  img.className = "cover";
  img.loading = "lazy";
  img.src = `https://ci.xiaohongshu.com/${it.cover_token}?imageView2/2/w/480/format/jpg`;
  img.onerror = () => {
    const d = document.createElement("div");
    d.className = "cover-missing";
    d.textContent = "🖼️";
    img.replaceWith(d);
  };
  return img;
}

function renderPreviews(items) {
  state.previews = items.map((it) => ({ ...it, checked: !!it.ok }));
  const ul = $("#previewList");
  ul.innerHTML = "";
  items.forEach((it, idx) => {
    const li = document.createElement("li");
    if (!it.ok) {
      li.className = "failed";
      li.innerHTML = `
        <div class="cover-missing">⚠️</div>
        <div>
          <div class="p-title">这篇没能解析</div>
          <div class="p-err"></div>
        </div>`;
      li.querySelector(".p-err").textContent = it.error || "未知原因";
      ul.appendChild(li);
      return;
    }
    li.innerHTML = `
      <input type="checkbox" class="p-check" checked />
      <div class="cover-slot"></div>
      <div>
        <div class="p-title"></div>
        <div class="p-meta">
          <span class="tags"></span><br/>
          <span class="p-sub"></span>
        </div>
      </div>
      <button class="p-open">打开原帖 ↗</button>
    `;
    li.querySelector(".cover-slot").replaceWith(coverCell(it));
    li.querySelector(".p-title").textContent = it.title;
    const tags = li.querySelector(".tags");
    for (const [label, cls] of typeTags(it)) {
      const t = document.createElement("span");
      t.className = "p-tag " + cls;
      t.textContent = label;
      tags.appendChild(t);
    }
    li.querySelector(".p-sub").textContent =
      it.author + (it.publish ? " · " + it.publish : "");
    const cb = li.querySelector(".p-check");
    cb.addEventListener("change", () => {
      state.previews[idx].checked = cb.checked;
      updateStartBtn();
    });
    li.querySelector(".p-open").addEventListener("click", async () => {
      const r = await apiCall("open_url", it.url);
      if (!r.ok) toast(r.error, "err");
    });
    ul.appendChild(li);
  });
  $("#previewCard").hidden = false;
  $("#previewTip").textContent = items.some((i) => !i.ok)
    ? "有解析失败的条目不影响其他条下载"
    : "";
  updateStartBtn();
}

function checkedLinks() {
  return state.previews.filter((p) => p.checked && p.ok);
}

function updateStartBtn() {
  const n = checkedLinks().length;
  $("#btnStart").textContent = `开始下载（${n} 篇）`;
  $("#btnStart").disabled = n === 0 || state.running;
}

async function doPreview() {
  const text = $("#input").value.trim();
  if (!text) return toast("请先粘贴分享链接", "err");
  if (state.running) return toast("正在下载中，等它跑完", "err");
  const btn = $("#btnPreview");
  btn.disabled = true;
  btn.textContent = "解析中…";
  const r = await apiCall("preview_links", text);
  btn.disabled = false;
  btn.textContent = "解析预览";
  if (!r.ok) return toast(r.error || "解析失败", "err");
  renderPreviews(r.items);
  const okCount = r.items.filter((i) => i.ok).length;
  toast(`解析完成：${okCount} 篇可以下载`, okCount ? "ok" : "err");
}

async function startSelected() {
  const links = checkedLinks();
  if (!links.length) return toast("请先勾选要下载的笔记", "err");
  const r = await apiCall(
    "start_selected",
    links.map((p) => ({ note_id: p.note_id, url: p.url }))
  );
  if (!r.ok) return toast(r.error || "启动失败", "err");
  toast(`已加入队列：${r.count} 篇`, "ok");
  document.querySelectorAll(".p-check").forEach((cb) => (cb.disabled = true));
  pollLoop();
}

/* ---------- 下载进度 ---------- */
const STATUS_LABEL = {
  pending: "等待",
  running: "进行中",
  done: "完成",
  skip: "跳过",
  failed: "失败",
};

function renderStatus(snap) {
  const card = $("#tasksCard");
  if (!snap.items.length) return;
  card.hidden = false;
  const c = snap.counts;
  $("#taskSummary").textContent =
    `共 ${snap.items.length} 篇 · 完成 ${c.done} · 跳过 ${c.skip} · 失败 ${c.failed}` +
    (snap.phase === "running" ? " · 下载中…" : snap.phase === "done" ? " · 全部结束" : "");
  $("#taskFolder").textContent = snap.folder ? "位置：" + snap.folder : "";

  const ul = $("#taskList");
  ul.innerHTML = "";
  for (const it of snap.items) {
    const li = document.createElement("li");
    const label = it.folder || it.display;
    li.innerHTML = `
      <span class="name"></span>
      <span class="status st-${it.status}">${STATUS_LABEL[it.status] || it.status}</span>
      <span class="progress ${it.status === "running" ? "on" : ""}"><i style="width:${it.progress}%"></i></span>
      ${it.reason ? `<span class="reason"></span>` : ""}
      ${it.hint ? `<span class="hint"></span>` : ""}
    `;
    li.querySelector(".name").textContent = label;
    if (it.reason) li.querySelector(".reason").textContent = it.reason;
    if (it.hint) li.querySelector(".hint").textContent = "💡 " + it.hint;
    ul.appendChild(li);
  }
  const running = snap.phase === "running";
  state.running = running;
  updateStartBtn();
  $("#btnPreview").disabled = running;
}

function stopPoll() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function pollLoop() {
  stopPoll();
  state.pollTimer = setInterval(async () => {
    const r = await apiCall("poll_status");
    if (!r.ok) return;
    renderStatus(r);
    if (r.phase === "done") {
      stopPoll();
      const c = r.counts;
      if (c.failed === 0) toast(`全部完成：${c.done} 篇成功，${c.skip} 篇已存在`, "ok");
      else toast(`结束：成功 ${c.done}，失败 ${c.failed}（原因见列表）`, "err");
    }
  }, 800);
}

/* ---------- 登录救援 ---------- */
function watchLogin() {
  stopLoginWatch();
  state.loginTimer = setInterval(async () => {
    const r = await apiCall("login_state");
    if (r.ok && r.logged_in) {
      stopLoginWatch();
      toast("登录身份已保存，视频原画与受限笔记都能下了", "ok");
      const s = await apiCall("get_settings");
      if (s.ok) applySettings(s);
    }
  }, 2000);
  setTimeout(stopLoginWatch, 6 * 60 * 1000);
}
function stopLoginWatch() {
  if (state.loginTimer) {
    clearInterval(state.loginTimer);
    state.loginTimer = null;
  }
}

/* ---------- 事件绑定 ---------- */
async function bind() {
  const s = await apiCall("get_settings");
  if (s.ok) applySettings(s);

  $("#btnDisclaimer").addEventListener("click", () => showDisclaimer(false));
  $("#btnDisclaimerClose").addEventListener("click", () => {
    $("#disclaimerMask").hidden = true;
  });
  $("#btnAgree").addEventListener("click", async () => {
    const r = await apiCall("agree_disclaimer");
    if (r.ok) {
      $("#disclaimerMask").hidden = true;
      toast("感谢确认，开始使用吧", "ok");
    }
  });
  $("#btnDecline").addEventListener("click", async () => {
    const r = await apiCall("exit_app");
    if (r.ok && r.closed) return; // 桌面模式：窗口已关闭
    toast("未同意免责声明，暂时无法使用", "err");
  });

  $("#btnPreview").addEventListener("click", doPreview);
  $("#btnStart").addEventListener("click", startSelected);

  $("#btnOpenFolder").addEventListener("click", async () => {
    const r = await apiCall("open_folder");
    if (!r.ok) toast(r.error, "err");
  });

  $("#btnChooseDir").addEventListener("click", async () => {
    const r = await apiCall("choose_folder");
    if (r.ok && r.path) applySettings({ ...state.settings, save_dir: r.path });
  });

  $("#btnLoginWindow").addEventListener("click", async () => {
    const r = await apiCall("open_login_window");
    if (!r.ok) return toast(r.error, "err");
    toast("已打开登录页，扫码后窗口会自动关闭");
    watchLogin();
  });

  $("#btnSaveCookie").addEventListener("click", async () => {
    const r = await apiCall("save_cookie_text", $("#cookieInput").value);
    const el = $("#cookieMsg");
    if (!r.ok) {
      el.textContent = r.error;
      el.style.color = "var(--err)";
      return;
    }
    el.textContent = "已保存";
    el.style.color = "var(--ok)";
    $("#cookieInput").value = "";
    const s2 = await apiCall("get_settings");
    if (s2.ok) applySettings(s2);
    toast("登录身份已保存", "ok");
  });

  $("#btnClearCookie").addEventListener("click", async () => {
    const r = await apiCall("clear_cookie");
    if (r.ok) {
      $("#cookieMsg").textContent = "";
      const s2 = await apiCall("get_settings");
      if (s2.ok) applySettings(s2);
      toast("已清除登录身份，恢复免登录游客模式", "ok");
    }
  });
}

bind();
