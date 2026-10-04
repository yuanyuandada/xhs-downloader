/* 小红书下载器 - 前端逻辑（pywebview 与网页调试模式通用） */
"use strict";

const $ = (sel) => document.querySelector(sel);

const state = {
  bridge: null,
  settings: null,
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
}

/* ---------- 任务列表 ---------- */
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
    if (it.reason) li.querySelector(".reason").textContent = it.folder ? `${it.reason}` : it.reason;
    if (it.hint) li.querySelector(".hint").textContent = "💡 " + it.hint;
    ul.appendChild(li);
  }
  const running = snap.phase === "running";
  $("#btnStart").disabled = running;
  state.running = running;
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
      toast("登录身份已保存，正在用新身份重试会更稳", "ok");
      const s = await apiCall("get_settings");
      if (s.ok) applySettings(s);
    }
  }, 2000);
  // 最多盯 6 分钟
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

  $("#btnStart").addEventListener("click", async () => {
    const text = $("#input").value.trim();
    if (!text) return toast("请先粘贴分享链接", "err");
    const r = await apiCall("start_download", text);
    if (!r.ok) return toast(r.error || "启动失败", "err");
    toast(`已加入队列：${r.count} 篇`, "ok");
    pollLoop();
  });

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
    const s = await apiCall("get_settings");
    if (s.ok) applySettings(s);
    toast("登录身份已保存", "ok");
  });

  $("#btnClearCookie").addEventListener("click", async () => {
    const r = await apiCall("clear_cookie");
    if (r.ok) {
      $("#cookieMsg").textContent = "";
      const s = await apiCall("get_settings");
      if (s.ok) applySettings(s);
      toast("已清除登录身份，恢复免登录游客模式", "ok");
    }
  });
}

bind();
