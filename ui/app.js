/**
 * Hermes Agent Control Panel - Frontend Application Logic
 */

// API Base URL (Relative for both pywebview and web server)
const API_BASE = "";

// State
let state = {
  hermesInstalled: false,
  hermesPath: "",
  services: [],
  config: {},
  originalConfig: {},
  logs: [],
  autoScroll: true
};

// SVG Icons for Actions & States (No Emoji)
const ICONS = {
  spinner: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="spin-icon"><circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/></svg>`,
  check: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`,
  cross: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`
};

// DOM Elements
const modulesTableBody = document.getElementById("modulesTableBody");
const consoleBody = document.getElementById("consoleBody");
const chkAutoScroll = document.getElementById("chkAutoScroll");
const systemDot = document.getElementById("systemDot");
const systemStatus = document.getElementById("systemStatus");
const statCpu = document.getElementById("statCpu");
const statRam = document.getElementById("statRam");
const hermesEnvStatus = document.getElementById("hermesEnvStatus");
const footerHermesExe = document.getElementById("footerHermesExe");

// Quick config elements
const quickProvider = document.getElementById("quickProvider");
const quickModel = document.getElementById("quickModel");
const presetModels = document.getElementById("presetModels");
const quickBaseUrl = document.getElementById("quickBaseUrl");
const quickApiKey = document.getElementById("quickApiKey");
const btnToggleKey = document.getElementById("btnToggleKey");
const iconEyeOpen = document.getElementById("iconEyeOpen");
const iconEyeClosed = document.getElementById("iconEyeClosed");
const btnApplyModel = document.getElementById("btnApplyModel");
const btnQuickSave = document.getElementById("btnQuickSave");

// Modals
const modalSettings = document.getElementById("modalSettings");
const modalApiTest = document.getElementById("modalApiTest");
const modalExplorer = document.getElementById("modalExplorer");

// Fetch helpers
async function apiGet(path) {
  try {
    const res = await fetch(API_BASE + path);
    return await res.json();
  } catch (err) {
    console.error("GET error", path, err);
    return null;
  }
}

async function apiPost(path, body = {}) {
  try {
    const res = await fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    return await res.json();
  } catch (err) {
    console.error("POST error", path, err);
    return { success: false, message: String(err) };
  }
}

// Service Actions
async function toggleService(key, currentStatus) {
  const action = currentStatus === "RUNNING" ? "stop" : "start";
  renderTableLoading(key);
  const res = await apiPost(`/api/service/${key}/${action}`);
  await updateStatus();
  await updateLogs();
}

async function restartService(key) {
  renderTableLoading(key);
  await apiPost(`/api/service/${key}/restart`);
  await updateStatus();
  await updateLogs();
}

function renderTableLoading(key) {
  const row = document.getElementById(`row-${key}`);
  if (row) {
    const statusCell = row.querySelector(".cell-status");
    if (statusCell) {
      statusCell.innerHTML = `<span class="badge-status starting">WAIT...</span>`;
    }
  }
}

// Update Status from Backend
async function updateStatus() {
  const data = await apiGet("/api/status");
  if (!data) return;

  state.hermesInstalled = data.hermes_installed;
  state.hermesPath = data.hermes_path;
  state.services = data.services || [];

  // Update System Bar
  if (data.system) {
    statCpu.textContent = data.system.cpu;
    statRam.textContent = data.system.ram;
  }

  if (state.hermesInstalled) {
    systemDot.style.backgroundColor = "var(--accent-success)";
    systemStatus.textContent = "Ready";
    hermesEnvStatus.textContent = "Installed";
    hermesEnvStatus.style.color = "#34d399";
    footerHermesExe.textContent = state.hermesPath;
  } else {
    systemDot.style.backgroundColor = "var(--accent-warning)";
    systemStatus.textContent = "Installing...";
    hermesEnvStatus.textContent = "Pending";
    hermesEnvStatus.style.color = "#fbbf24";
    footerHermesExe.textContent = data.hermes_path;
  }

  // Check Start All progress from backend
  if (data.start_all_progress) {
    const prog = data.start_all_progress;
    if (prog.in_progress) {
      state.isStartingAll = true;
      btnStartAll.disabled = true;
      const stepText = prog.step > 0 ? ` (${prog.step}/${prog.total})` : "";
      btnStartAll.innerHTML = `${ICONS.spinner} Starting${stepText}...`;
    } else if (state.isStartingAll) {
      resetStartAllButton();
    }
  }

  // Render Table
  renderModulesTable();
}

function resetStartAllButton() {
  state.isStartingAll = false;
  if (state.startAllTimeoutTimer) {
    clearTimeout(state.startAllTimeoutTimer);
    state.startAllTimeoutTimer = null;
  }
  btnStartAll.disabled = false;
  btnStartAll.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg> Start All`;
}

// Render Modules Table
function renderModulesTable() {
  modulesTableBody.innerHTML = "";

  state.services.forEach(svc => {
    const tr = document.createElement("tr");
    tr.id = `row-${svc.key}`;

    const isRunning = svc.status === "RUNNING";
    const statusClass = svc.status.toLowerCase();
    const pidText = svc.pid ? svc.pid : "-";

    // Accurate Port representation:
    // Gateway is a background messaging worker/bot (not a listening TCP port)
    // Serve is the RPC backend on 8642
    // Dashboard is on 9119, WebUI is on 8645
    let portText = "";
    if (svc.port) {
      portText = svc.port;
    } else if (svc.key === "gateway") {
      portText = `<span class="tag-worker">Daemon</span>`;
    } else {
      portText = `<span class="tag-worker">Worker</span>`;
    }

    // Action button
    const btnClass = isRunning ? "btn-table-stop" : "btn-table-start";
    const btnText = isRunning ? "Stop" : "Start";

    let extraButtons = "";
    if (svc.key === "dashboard" && isRunning) {
      extraButtons += `<a href="http://127.0.0.1:9119" target="_blank" class="btn btn-sm btn-outline" style="text-decoration:none;">Open ↗</a>`;
    } else if (svc.key === "webui" && isRunning) {
      extraButtons += `<a href="http://127.0.0.1:${svc.port}" target="_blank" class="btn btn-sm btn-outline" style="text-decoration:none;">Open ↗</a>`;
    } else if (svc.key === "serve" && isRunning) {
      extraButtons += `<button class="btn btn-sm btn-outline" onclick="openApiTester()">Test API</button>`;
    }

    // Error message badge under module description if available
    const errorMarkup = svc.error ? `<div class="module-error-badge" title="${escapeHtml(svc.error)}">${escapeHtml(svc.error)}</div>` : "";

    tr.innerHTML = `
      <td>
        <div class="module-name">${svc.name}</div>
        <div class="module-desc">${svc.description}</div>
        ${errorMarkup}
      </td>
      <td class="cell-status">
        <span class="badge-status ${statusClass}">${svc.status}</span>
      </td>
      <td class="cell-pid">${pidText}</td>
      <td class="cell-port">${portText}</td>
      <td class="cell-actions">
        <button class="btn btn-sm ${btnClass}" onclick="toggleService('${svc.key}', '${svc.status}')">${btnText}</button>
        ${extraButtons}
        <button class="btn btn-sm btn-outline" onclick="openSettingsModal()" title="Config">Config</button>
      </td>
    `;
    modulesTableBody.appendChild(tr);
  });
}

// Logs Update
async function updateLogs() {
  const data = await apiGet("/api/logs");
  if (!data || !data.logs) return;

  const currentCount = state.logs.length;
  if (data.logs.length === currentCount && currentCount > 0) return;

  state.logs = data.logs;
  consoleBody.innerHTML = "";

  state.logs.forEach(log => {
    const div = document.createElement("div");
    div.className = "log-line";
    const lvlClass = `log-level-${log.level.toLowerCase()}`;

    div.innerHTML = `
      <span class="log-time">[${log.timestamp}]</span>
      <span class="log-source">[${log.source.toUpperCase()}]</span>
      <span class="${lvlClass}">${escapeHtml(log.message)}</span>
    `;
    consoleBody.appendChild(div);
  });

  if (chkAutoScroll.checked) {
    consoleBody.scrollTop = consoleBody.scrollHeight;
  }
}

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}

// Config Loader & Dirty Check
async function loadConfig() {
  const cfg = await apiGet("/api/config");
  if (!cfg) return;

  state.config = cfg;
  state.originalConfig = {
    provider: cfg.provider || "tokengateway",
    model_name: cfg.model_name || "glm-5.3",
    base_url: cfg.base_url || "",
    api_key: cfg.api_key || ""
  };

  quickProvider.value = state.originalConfig.provider;
  quickModel.value = state.originalConfig.model_name;
  quickBaseUrl.value = state.originalConfig.base_url;
  quickApiKey.value = state.originalConfig.api_key;

  // Settings Modal fields
  document.getElementById("cfgOpenRouterKey").value = cfg.openrouter_key || "";
  document.getElementById("cfgNousPortalKey").value = cfg.nous_portal_key || "";
  document.getElementById("cfgOpenAIKey").value = cfg.openai_key || "";
  document.getElementById("cfgAnthropicKey").value = cfg.anthropic_key || "";
  document.getElementById("cfgGroqKey").value = cfg.groq_key || "";
  document.getElementById("cfgDeepSeekKey").value = cfg.deepseek_key || "";
  document.getElementById("cfgTemperature").value = cfg.temperature || 0.7;
  document.getElementById("cfgMaxTokens").value = cfg.max_tokens || 4096;
  document.getElementById("cfgGatewayPort").value = cfg.api_server_port || 8642;
  document.getElementById("cfgTelegramToken").value = cfg.telegram_token || "";
  document.getElementById("cfgDiscordToken").value = cfg.discord_token || "";

  // Reset Save button state to disabled
  resetSaveButtons();
}

function checkConfigDirty() {
  const isDirty = (
    quickProvider.value !== (state.originalConfig.provider || "") ||
    quickModel.value !== (state.originalConfig.model_name || "") ||
    quickBaseUrl.value !== (state.originalConfig.base_url || "") ||
    quickApiKey.value !== (state.originalConfig.api_key || "")
  );

  btnQuickSave.disabled = !isDirty;
  btnApplyModel.disabled = !isDirty;
}

function resetSaveButtons() {
  btnQuickSave.disabled = true;
  btnApplyModel.disabled = true;
  btnQuickSave.className = "btn-save-state btn-sm";
  btnApplyModel.className = "btn-save-state btn-sm";
  btnQuickSave.innerHTML = `Save`;
  btnApplyModel.innerHTML = `Apply Changes`;
}

// Quick Config Save with 4 States: Idle, Saving, Saved (SVG), Error (SVG)
async function saveQuickConfig() {
  const payload = {
    provider: quickProvider.value,
    model_name: quickModel.value,
    base_url: quickBaseUrl.value,
    api_key: quickApiKey.value,
    temperature: state.config.temperature || 0.7,
    max_tokens: state.config.max_tokens || 4096
  };

  // State: Saving
  btnQuickSave.disabled = true;
  btnApplyModel.disabled = true;
  btnQuickSave.className = "btn-save-state btn-sm saving";
  btnApplyModel.className = "btn-save-state btn-sm saving";
  btnQuickSave.innerHTML = `${ICONS.spinner} Saving...`;
  btnApplyModel.innerHTML = `${ICONS.spinner} Saving...`;

  const res = await apiPost("/api/config", payload);

  if (res && res.success) {
    // State: Success
    btnQuickSave.className = "btn-save-state btn-sm saved";
    btnApplyModel.className = "btn-save-state btn-sm saved";
    btnQuickSave.innerHTML = `${ICONS.check} Saved`;
    btnApplyModel.innerHTML = `${ICONS.check} Applied`;

    await loadConfig();
    await updateLogs();

    setTimeout(() => {
      resetSaveButtons();
    }, 1500);
  } else {
    // State: Error
    btnQuickSave.className = "btn-save-state btn-sm error";
    btnApplyModel.className = "btn-save-state btn-sm error";
    btnQuickSave.innerHTML = `${ICONS.cross} Failed`;
    btnApplyModel.innerHTML = `${ICONS.cross} Failed`;

    setTimeout(() => {
      btnQuickSave.disabled = false;
      btnApplyModel.disabled = false;
      btnQuickSave.className = "btn-save-state btn-sm";
      btnApplyModel.className = "btn-save-state btn-sm";
      btnQuickSave.innerHTML = `Save`;
      btnApplyModel.innerHTML = `Apply Changes`;
    }, 2000);
  }
}

// Dirty Change Listeners
[quickProvider, quickModel, quickBaseUrl, quickApiKey].forEach(el => {
  el.addEventListener("input", checkConfigDirty);
  el.addEventListener("change", checkConfigDirty);
});

// Presets Dropdown
presetModels.addEventListener("change", (e) => {
  if (e.target.value) {
    quickModel.value = e.target.value;
    checkConfigDirty();
  }
});

quickProvider.addEventListener("change", (e) => {
  const p = e.target.value;
  if (p === "tokengateway") {
    quickBaseUrl.value = "https://tokengateway.ai.id/v1";
    quickModel.value = "glm-5.3";
  } else if (p === "ollama") {
    quickBaseUrl.value = "http://localhost:11434/v1";
    quickModel.value = "llama3.1:8b";
  } else if (p === "lmstudio") {
    quickBaseUrl.value = "http://localhost:1234/v1";
  } else if (p === "openrouter") {
    quickBaseUrl.value = "https://openrouter.ai/api/v1";
    quickModel.value = "nousresearch/hermes-3-llama-3.1-405b";
  } else if (p === "nous") {
    quickBaseUrl.value = "https://portal.nousresearch.com/v1";
    quickModel.value = "Hermes-3-Llama-3.1-405B";
  } else {
    quickBaseUrl.value = "";
  }
  checkConfigDirty();
});

// Toggle Password Visibility with SVG Icons
btnToggleKey.addEventListener("click", () => {
  if (quickApiKey.type === "password") {
    quickApiKey.type = "text";
    iconEyeOpen.style.display = "none";
    iconEyeClosed.style.display = "inline";
  } else {
    quickApiKey.type = "password";
    iconEyeOpen.style.display = "inline";
    iconEyeClosed.style.display = "none";
  }
});

btnApplyModel.addEventListener("click", saveQuickConfig);
btnQuickSave.addEventListener("click", saveQuickConfig);

// Toolbar Buttons
const btnStartAll = document.getElementById("btnStartAll");
const btnStopAll = document.getElementById("btnStopAll");

btnStartAll.addEventListener("click", async () => {
  if (state.isStartingAll) return; // Prevent double-click
  state.isStartingAll = true;
  btnStartAll.disabled = true;
  btnStartAll.innerHTML = `${ICONS.spinner} Starting (1/4)...`;
  btnStopAll.disabled = false; // Stop All must remain enabled!

  // Fallback safety timeout (90 seconds)
  if (state.startAllTimeoutTimer) clearTimeout(state.startAllTimeoutTimer);
  state.startAllTimeoutTimer = setTimeout(() => {
    resetStartAllButton();
  }, 90000);

  try {
    await apiPost("/api/services/start_all");
  } catch (err) {
    console.error("Start All trigger error:", err);
    resetStartAllButton();
  } finally {
    await updateStatus();
    await updateLogs();
  }
});

btnStopAll.addEventListener("click", async () => {
  resetStartAllButton();
  btnStopAll.disabled = true;
  const originalStopHtml = btnStopAll.innerHTML;
  btnStopAll.innerHTML = `${ICONS.spinner} Stopping...`;

  try {
    await apiPost("/api/services/stop_all");
  } catch (err) {
    console.error("Stop All error:", err);
  } finally {
    btnStopAll.innerHTML = originalStopHtml;
    btnStopAll.disabled = false;
    await updateStatus();
    await updateLogs();
  }
});

document.getElementById("btnLaunchShell").addEventListener("click", () => {
  apiPost("/api/terminal/launch", { mode: "shell" });
});

document.getElementById("btnLaunchChat").addEventListener("click", () => {
  apiPost("/api/terminal/launch", { mode: "chat" });
});

document.getElementById("btnLaunchTui").addEventListener("click", () => {
  apiPost("/api/terminal/launch", { mode: "tui" });
});

document.getElementById("btnLaunchYolo").addEventListener("click", () => {
  apiPost("/api/terminal/launch", { mode: "yolo" });
});

document.getElementById("btnRefresh").addEventListener("click", async () => {
  await updateStatus();
  await updateLogs();
});

document.getElementById("btnClearLog").addEventListener("click", async () => {
  await apiPost("/api/logs/clear");
  await updateLogs();
});

document.getElementById("btnCopyLog").addEventListener("click", () => {
  const text = state.logs.map(l => `[${l.timestamp}] [${l.source}] ${l.message}`).join("\n");
  navigator.clipboard.writeText(text);
});

// Modals Handlers
function openSettingsModal() {
  modalSettings.classList.add("active");
}

function closeSettingsModal() {
  modalSettings.classList.remove("active");
}

document.getElementById("btnOpenConfig").addEventListener("click", openSettingsModal);
document.getElementById("btnCloseSettings").addEventListener("click", closeSettingsModal);
document.getElementById("btnCancelSettings").addEventListener("click", closeSettingsModal);

// Settings Tab switching
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    const target = document.getElementById(btn.dataset.tab);
    if (target) target.classList.add("active");
  });
});

document.getElementById("btnSaveFullSettings").addEventListener("click", async () => {
  const payload = {
    provider: quickProvider.value,
    model_name: quickModel.value,
    base_url: quickBaseUrl.value,
    api_key: quickApiKey.value,
    openrouter_key: document.getElementById("cfgOpenRouterKey").value,
    nous_portal_key: document.getElementById("cfgNousPortalKey").value,
    openai_key: document.getElementById("cfgOpenAIKey").value,
    anthropic_key: document.getElementById("cfgAnthropicKey").value,
    groq_key: document.getElementById("cfgGroqKey").value,
    deepseek_key: document.getElementById("cfgDeepSeekKey").value,
    temperature: parseFloat(document.getElementById("cfgTemperature").value) || 0.7,
    max_tokens: parseInt(document.getElementById("cfgMaxTokens").value) || 4096,
    api_server_port: document.getElementById("cfgGatewayPort").value,
    telegram_token: document.getElementById("cfgTelegramToken").value,
    discord_token: document.getElementById("cfgDiscordToken").value
  };

  const res = await apiPost("/api/config", payload);
  if (res && res.success) {
    closeSettingsModal();
    await loadConfig();
    await updateLogs();
  }
});

// Explorer Modal
document.getElementById("btnOpenFolder").addEventListener("click", () => {
  modalExplorer.classList.add("active");
});
document.getElementById("btnCloseExplorer").addEventListener("click", () => {
  modalExplorer.classList.remove("active");
});
document.querySelectorAll(".explorer-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.target;
    apiPost("/api/open_folder", { target });
    modalExplorer.classList.remove("active");
  });
});

// API Tester Modal
function openApiTester() {
  modalApiTest.classList.add("active");
}
document.getElementById("btnTestApi").addEventListener("click", openApiTester);
document.getElementById("btnCloseApiTest").addEventListener("click", () => modalApiTest.classList.remove("active"));
document.getElementById("btnCloseApiTestBtn").addEventListener("click", () => modalApiTest.classList.remove("active"));

document.getElementById("btnSendTestPrompt").addEventListener("click", async () => {
  const prompt = document.getElementById("txtTestPrompt").value;
  const box = document.getElementById("boxApiResponse");
  const btn = document.getElementById("btnSendTestPrompt");

  btn.disabled = true;
  box.textContent = "Connecting to Hermes RPC Backend (127.0.0.1:8642)...";
  box.style.color = "#94a3b8";

  const res = await apiPost("/api/chat/test", { prompt, port: 8642 });
  btn.disabled = false;

  if (res && res.success) {
    box.textContent = res.response;
    box.style.color = "#34d399";
  } else {
    box.textContent = "Error: " + (res.error || res.message || "Request failed");
    box.style.color = "#f87171";
  }
  await updateLogs();
});

// Init
window.addEventListener("DOMContentLoaded", async () => {
  await loadConfig();
  await updateStatus();
  await updateLogs();

  // Polling loop
  setInterval(async () => {
    await updateStatus();
    await updateLogs();
  }, 2000);
});
