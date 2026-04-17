const POLL_INTERVAL_MS = 15000;

class UnauthorizedError extends Error {
  constructor(message = "请先登录") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

const state = {
  editingUserId: null,
  latestRunId: null,
  pollTimerId: null,
  desktopNotificationEnabled: window.localStorage.getItem("desktopNotificationEnabled") === "1",
};

const userForm = document.querySelector("#userForm");
const formTitle = document.querySelector("#formTitle");
const submitButton = document.querySelector("#submitButton");
const resetFormButton = document.querySelector("#resetFormButton");
const refreshUsersButton = document.querySelector("#refreshUsersButton");
const refreshRunsButton = document.querySelector("#refreshRunsButton");
const desiredStatusInput = document.querySelector("#desiredStatusInput");
const offCampusFields = document.querySelector("#offCampusFields");
const usersTableBody = document.querySelector("#usersTableBody");
const usersEmpty = document.querySelector("#usersEmpty");
const runsTableBody = document.querySelector("#runsTableBody");
const runsEmpty = document.querySelector("#runsEmpty");
const healthBadge = document.querySelector("#healthBadge");
const healthMeta = document.querySelector("#healthMeta");
const passwordInput = document.querySelector("#passwordInput");
const passwordHelp = document.querySelector("#passwordHelp");
const authOverlay = document.querySelector("#authOverlay");
const loginForm = document.querySelector("#loginForm");
const loginPasswordInput = document.querySelector("#loginPasswordInput");
const loginError = document.querySelector("#loginError");
const logoutButton = document.querySelector("#logoutButton");
const appLayout = document.querySelector("#appLayout");
const toastStack = document.querySelector("#toastStack");
const notificationButton = document.querySelector("#notificationButton");

function formatApiError(data, fallbackMessage) {
  if (!data) {
    return fallbackMessage;
  }
  if (typeof data.detail === "string" && data.detail.trim()) {
    return data.detail;
  }
  if (Array.isArray(data.detail) && data.detail.length > 0) {
    const messages = data.detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item.msg === "string") {
          return item.msg;
        }
        return "";
      })
      .filter(Boolean);
    if (messages.length > 0) {
      return messages.join("\n");
    }
  }
  if (typeof data.message === "string" && data.message.trim()) {
    return data.message;
  }
  return fallbackMessage;
}

function validatePayload(payload, isEditing) {
  if (!payload.student_no) {
    return "请先填写学号。";
  }
  if (!isEditing && !payload.password) {
    return "新增账号时必须填写密码。";
  }
  if (!payload.schedule_time) {
    return "请先填写每日执行基准时间。";
  }
  if (payload.desired_status === "不在校") {
    if (!payload.off_campus_city) {
      return "选择不在校时必须填写省/市/区。";
    }
    if (!payload.off_campus_district) {
      return "选择不在校时必须填写详细地址。";
    }
    if (!payload.off_campus_reason) {
      return "选择不在校时必须填写事由。";
    }
  }
  return null;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function api(path, options = {}) {
  const init = { ...options };
  const allowUnauthorized = Boolean(init.allowUnauthorized);
  delete init.allowUnauthorized;
  const headers = new Headers(init.headers || {});
  if (!(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  init.headers = headers;

  const response = await fetch(path, init);
  if (response.status === 401) {
    if (allowUnauthorized) {
      let message = "请求未通过鉴权";
      try {
        const data = await response.json();
        message = formatApiError(data, message);
      } catch {
        const text = await response.text();
        if (text) {
          message = text;
        }
      }
      throw new Error(message);
    }
    showAuthOverlay("登录状态已失效，请重新输入管理密码。");
    throw new UnauthorizedError();
  }
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const data = await response.json();
      message = formatApiError(data, message);
    } catch {
      const text = await response.text();
      if (text) {
        message = text;
      }
    }
    throw new Error(message);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function updateNotificationButton() {
  if (!("Notification" in window)) {
    notificationButton.textContent = "当前浏览器不支持桌面提醒";
    notificationButton.disabled = true;
    return;
  }
  notificationButton.disabled = false;
  if (Notification.permission === "denied") {
    state.desktopNotificationEnabled = false;
    window.localStorage.removeItem("desktopNotificationEnabled");
    notificationButton.textContent = "桌面提醒已被浏览器拒绝";
    return;
  }
  notificationButton.textContent = state.desktopNotificationEnabled ? "关闭桌面提醒" : "启用桌面提醒";
}

function showToast(message, kind = "success") {
  const toast = document.createElement("div");
  toast.className = `toast toast-${kind}`;
  toast.textContent = message;
  toastStack.appendChild(toast);
  window.setTimeout(() => {
    toast.classList.add("toast-leaving");
    window.setTimeout(() => toast.remove(), 220);
  }, 3600);
}

function showAuthOverlay(message = "") {
  authOverlay.classList.remove("hidden");
  appLayout.classList.add("hidden");
  logoutButton.classList.add("hidden");
  loginError.textContent = message;
  loginError.classList.toggle("hidden", !message);
  healthBadge.dataset.state = "warning";
  healthBadge.textContent = "请先登录";
  healthMeta.textContent = "登录后显示服务状态，并在新任务完成时推送提醒。";
  stopPolling();
}

function hideAuthOverlay() {
  authOverlay.classList.add("hidden");
  appLayout.classList.remove("hidden");
  logoutButton.classList.remove("hidden");
  loginError.textContent = "";
  loginError.classList.add("hidden");
  loginForm.reset();
}

function stopPolling() {
  if (state.pollTimerId !== null) {
    window.clearInterval(state.pollTimerId);
    state.pollTimerId = null;
  }
}

function startPolling() {
  stopPolling();
  state.pollTimerId = window.setInterval(() => {
    refreshRunsWithNotifications().catch((error) => {
      if (!(error instanceof UnauthorizedError)) {
        console.error(error);
      }
    });
  }, POLL_INTERVAL_MS);
}

function toggleOffCampusFields() {
  const isOffCampus = desiredStatusInput.value === "不在校";
  offCampusFields.classList.toggle("hidden", !isOffCampus);
}

function resetForm() {
  state.editingUserId = null;
  userForm.reset();
  passwordInput.placeholder = "新增账号时请手动输入密码";
  passwordHelp.textContent = "系统不会预填默认密码。新增时必填；仅编辑已有账号时可留空并保留当前已存密码。";
  document.querySelector("#scheduleTimeInput").value = "07:30";
  document.querySelector("#enabledInput").checked = true;
  document.querySelector("#overwriteInput").checked = false;
  desiredStatusInput.value = "在校";
  formTitle.textContent = "新增账号";
  submitButton.textContent = "保存账号";
  toggleOffCampusFields();
}

function fillForm(user) {
  state.editingUserId = user.id;
  formTitle.textContent = `编辑账号 #${user.id}`;
  submitButton.textContent = "更新账号";
  document.querySelector("#labelInput").value = user.label || "";
  document.querySelector("#studentNoInput").value = user.student_no || "";
  passwordInput.value = "";
  passwordInput.placeholder = "留空则保留当前已存密码";
  passwordHelp.textContent = "当前不会展示或预填已存密码。只有你主动输入新密码时，系统才会更新它。";
  document.querySelector("#scheduleTimeInput").value = user.schedule_time;
  document.querySelector("#desiredStatusInput").value = user.desired_status;
  document.querySelector("#cityInput").value = user.off_campus_city || "";
  document.querySelector("#districtInput").value = user.off_campus_district || "";
  document.querySelector("#reasonInput").value = user.off_campus_reason || "";
  document.querySelector("#enabledInput").checked = Boolean(user.enabled);
  document.querySelector("#overwriteInput").checked = Boolean(user.overwrite_existing);
  toggleOffCampusFields();
}

function resultKind(outcome) {
  if (outcome === "success") return "success";
  if (outcome === "failed") return "danger";
  return "warning";
}

function summarizeRun(run) {
  const displayName = run.user_label || run.student_no;
  const outcomeText =
    run.outcome === "success" ? "执行成功" : run.outcome === "failed" ? "执行失败" : "无需重复提交";
  return `${displayName} ${outcomeText}：${run.message}`;
}

function announceRuns(runs) {
  if (runs.length === 0) {
    return;
  }
  const latestRun = runs[0];
  showToast(summarizeRun(latestRun), resultKind(latestRun.outcome));
  if (
    state.desktopNotificationEnabled &&
    "Notification" in window &&
    Notification.permission === "granted"
  ) {
    const title = latestRun.triggered_by === "scheduler" ? "定时任务已完成" : "手动任务已完成";
    new Notification(title, {
      body: summarizeRun(latestRun),
    });
  }
}

function renderUsers(users) {
  usersTableBody.innerHTML = users
    .map((user) => {
      const displayName = user.label || `账号 ${user.student_no}`;
      const targetText =
        user.desired_status === "在校"
          ? "在校"
          : `不在校 / ${escapeHtml(user.off_campus_city)} ${escapeHtml(user.off_campus_district)} / ${escapeHtml(user.off_campus_reason)}`;
      const strategyText = user.overwrite_existing ? "允许覆盖" : "不覆盖";
      return `
        <tr>
          <td>
            <div class="identity-block">
              <strong>${escapeHtml(displayName)}</strong>
              <span>${escapeHtml(user.student_no)}</span>
            </div>
          </td>
          <td>${escapeHtml(user.schedule_time)} 起随机</td>
          <td class="user-target">${targetText}</td>
          <td class="meta-text">${strategyText}</td>
          <td class="status-cell">
            <span class="status-pill ${user.enabled ? "success" : "warning"}">
              ${user.enabled ? "已启用" : "已停用"}
            </span>
          </td>
          <td class="actions-cell">
            <div class="inline-actions" aria-label="账号操作">
              <button class="table-action" data-kind="run" data-id="${user.id}">立即执行</button>
              <button class="table-action" data-kind="edit" data-id="${user.id}">编辑</button>
              <button class="table-action" data-kind="delete" data-id="${user.id}">删除</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
  usersEmpty.classList.toggle("hidden", users.length > 0);
}

function renderRuns(runs) {
  runsTableBody.innerHTML = runs
    .map((run) => {
      const displayName = run.user_label || run.student_no;
      const trigger = run.triggered_by === "scheduler" ? "定时器" : "手动";
      return `
        <tr>
          <td>${escapeHtml(run.created_at.replace("T", " ").slice(0, 19))}</td>
          <td>
            <div class="identity-block">
              <strong>${escapeHtml(displayName)}</strong>
              <span>${escapeHtml(run.student_no)}</span>
            </div>
          </td>
          <td class="meta-text">${trigger}</td>
          <td>
            <span class="status-pill ${resultKind(run.outcome)}">
              ${escapeHtml(run.outcome)}
            </span>
          </td>
          <td>${escapeHtml(run.message)}</td>
        </tr>
      `;
    })
    .join("");
  runsEmpty.classList.toggle("hidden", runs.length > 0);
}

function syncRunNotifications(runs, shouldNotify) {
  if (runs.length === 0) {
    state.latestRunId = null;
    return;
  }
  if (state.latestRunId === null) {
    state.latestRunId = runs[0].id;
    return;
  }
  const newRuns = runs
    .filter((run) => run.id > state.latestRunId)
    .sort((left, right) => left.id - right.id);
  state.latestRunId = Math.max(state.latestRunId, runs[0].id);
  if (shouldNotify) {
    announceRuns(newRuns);
  }
}

async function loadHealth() {
  try {
    const health = await api("/api/health");
    healthBadge.dataset.state = "ok";
    healthBadge.textContent = "后端在线";
    healthMeta.textContent = `${health.timezone} · 已托管 ${health.user_count} 个账号`;
  } catch (error) {
    healthBadge.dataset.state = "error";
    healthBadge.textContent = "连接失败";
    healthMeta.textContent = error.message;
  }
}

async function loadUsers() {
  const users = await api("/api/users");
  renderUsers(users);
}

async function loadRuns() {
  const runs = await api("/api/runs?limit=80");
  renderRuns(runs);
  syncRunNotifications(runs, false);
}

async function refreshRunsWithNotifications() {
  const runs = await api("/api/runs?limit=80");
  renderRuns(runs);
  syncRunNotifications(runs, true);
}

async function refreshAll() {
  await Promise.all([loadHealth(), loadUsers(), loadRuns()]);
}

function collectPayload() {
  const password = document.querySelector("#passwordInput").value.trim();
  const payload = {
    label: document.querySelector("#labelInput").value.trim(),
    student_no: document.querySelector("#studentNoInput").value.trim(),
    password: password || null,
    schedule_time: document.querySelector("#scheduleTimeInput").value,
    desired_status: document.querySelector("#desiredStatusInput").value,
    off_campus_city: document.querySelector("#cityInput").value.trim(),
    off_campus_district: document.querySelector("#districtInput").value.trim(),
    off_campus_reason: document.querySelector("#reasonInput").value.trim(),
    enabled: document.querySelector("#enabledInput").checked,
    overwrite_existing: document.querySelector("#overwriteInput").checked,
  };
  if (payload.desired_status === "在校") {
    payload.off_campus_city = "";
    payload.off_campus_district = "";
    payload.off_campus_reason = "";
  }
  return payload;
}

async function restoreSession() {
  const session = await api("/api/session");
  if (!session.authenticated) {
    showAuthOverlay();
    return false;
  }
  hideAuthOverlay();
  await refreshAll();
  startPolling();
  return true;
}

userForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = collectPayload();
  const isEditing = Boolean(state.editingUserId);
  const validationMessage = validatePayload(payload, isEditing);
  if (validationMessage) {
    window.alert(validationMessage);
    return;
  }
  const body = JSON.stringify(payload);
  try {
    if (isEditing) {
      await api(`/api/users/${state.editingUserId}`, { method: "PUT", body });
    } else {
      await api("/api/users", { method: "POST", body });
    }
    resetForm();
    await refreshAll();
    showToast(isEditing ? "账号已更新" : "账号已保存", "success");
  } catch (error) {
    if (!(error instanceof UnauthorizedError)) {
      window.alert(error.message);
    }
  }
});

usersTableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-id]");
  if (!button) {
    return;
  }
  const userId = Number(button.dataset.id);
  const kind = button.dataset.kind;

  if (kind === "edit") {
    try {
      const users = await api("/api/users");
      const current = users.find((user) => user.id === userId);
      if (current) {
        fillForm(current);
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    } catch (error) {
      if (!(error instanceof UnauthorizedError)) {
        window.alert(error.message);
      }
    }
    return;
  }

  if (kind === "delete") {
    if (!window.confirm("确认删除这个托管账号吗？")) {
      return;
    }
    try {
      await api(`/api/users/${userId}`, { method: "DELETE" });
      if (state.editingUserId === userId) {
        resetForm();
      }
      await refreshAll();
      showToast("账号已删除", "warning");
    } catch (error) {
      if (!(error instanceof UnauthorizedError)) {
        window.alert(error.message);
      }
    }
    return;
  }

  if (kind === "run") {
    try {
      const result = await api(`/api/users/${userId}/run`, { method: "POST" });
      await refreshAll();
      showToast(summarizeRun(result), resultKind(result.outcome));
    } catch (error) {
      if (!(error instanceof UnauthorizedError)) {
        window.alert(error.message);
      }
    }
  }
});

desiredStatusInput.addEventListener("change", toggleOffCampusFields);
resetFormButton.addEventListener("click", resetForm);
refreshUsersButton.addEventListener("click", loadUsers);
refreshRunsButton.addEventListener("click", refreshRunsWithNotifications);

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  loginError.classList.add("hidden");
  try {
    await api("/api/session/login", {
      method: "POST",
      body: JSON.stringify({ password: loginPasswordInput.value.trim() }),
      allowUnauthorized: true,
    });
    hideAuthOverlay();
    await refreshAll();
    startPolling();
    showToast("已登录，任务完成后会在页面上提醒你。", "success");
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return;
    }
    loginError.textContent = error.message;
    loginError.classList.remove("hidden");
  }
});

logoutButton.addEventListener("click", async () => {
  try {
    await api("/api/session/logout", { method: "POST" });
  } catch (error) {
    if (!(error instanceof UnauthorizedError)) {
      window.alert(error.message);
    }
  }
  state.latestRunId = null;
  showAuthOverlay("已退出登录。");
});

notificationButton.addEventListener("click", async () => {
  if (!("Notification" in window) || Notification.permission === "denied") {
    updateNotificationButton();
    return;
  }
  if (state.desktopNotificationEnabled) {
    state.desktopNotificationEnabled = false;
    window.localStorage.removeItem("desktopNotificationEnabled");
    updateNotificationButton();
    showToast("桌面提醒已关闭。", "warning");
    return;
  }
  if (Notification.permission !== "granted") {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      updateNotificationButton();
      showToast("浏览器未授予桌面提醒权限。", "warning");
      return;
    }
  }
  state.desktopNotificationEnabled = true;
  window.localStorage.setItem("desktopNotificationEnabled", "1");
  updateNotificationButton();
  showToast("桌面提醒已启用。", "success");
});

resetForm();
toggleOffCampusFields();
updateNotificationButton();
restoreSession().catch((error) => {
  if (error instanceof UnauthorizedError) {
    return;
  }
  healthBadge.dataset.state = "error";
  healthBadge.textContent = "初始化失败";
  healthMeta.textContent = error.message;
  showAuthOverlay("服务初始化失败，请检查后端日志。");
});
