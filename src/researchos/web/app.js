const state = { view: "home", projects: [], projectId: null, activeRunId: null, detailRunId: null, detailRun: null, scopeRefinement: { runId: null, answers: [] }, modelConnected: false, modelRuntime: "ollama", modelDetails: [], modelRoles: {}, hfRepo: null, specter2Timer: null, modelUsageTimer: null, specter2Status: null, agentTrace: { runId: null, run: null, events: [], index: 0, revision: "", active: false, paused: false }, systemStatus: null, reportChat: { runId: null, ready: false, loaded: false, loading: false, messages: [], sending: false, draft: "", error: "", citationTargets: new Map() }, paperInsightId: null, paperInsightData: null, paperInsightTimer: null, paperInsightRequest: 0, analysisPapers: [], analysisPaperId: null, analysisPaperData: null, analysisPaperTimer: null, analysisPaperRequest: 0, paperSearchTimer: null, paperSearchSequence: 0, paperDiscoverySequence: 0, paperDiscoveryResults: [], paperChat: { analysisId: null, messages: [], sending: false }};
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHTML(value = "") {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}
function dateLabel(value) {
  if (!value) return "Just now";
  const date = new Date(value);
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}
function toast(message, type = "") {
  const item = document.createElement("div");
  item.className = `toast ${type}`;
  item.textContent = message;
  $("#toast-region").append(item);
  setTimeout(() => item.remove(), 4200);
}
async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Request failed (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function switchView(view, { resetScroll = true, writeHash = true } = {}) {
  if (!$(`#view-${view}`)) return;
  const changed = state.view !== view;
  state.view = view;
  const routeViews = ["home", "discover", "library", "analysis", "runs", "agents", "system"];
  if (writeHash && routeViews.includes(view) && window.location.hash !== `#${view}`) window.history.replaceState(null, "", `#${view}`);
  $$(".page-view").forEach((element) => element.classList.remove("active-view"));
  const page = $(`#view-${view}`);
  if (page) page.classList.add("active-view");
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  const titles = { home: "Overview", discover: "Find papers", library: "Paper library", analysis: "PDF analysis", runs: "Research runs", agents: "Agent team", system: "System Care", project: "Project workspace", detail: "Research report" };
  $("#current-page-title").textContent = titles[view] || "Overview";
  if (changed && resetScroll) window.scrollTo({ top: 0, behavior: "instant" });
  if (changed && view !== "library" && state.paperInsightId) {
    if (state.paperInsightTimer) clearTimeout(state.paperInsightTimer);
    state.paperInsightTimer = null; state.paperInsightRequest += 1;
  }
  if (changed && view !== "analysis") {
    if (state.analysisPaperTimer) clearTimeout(state.analysisPaperTimer);
    state.analysisPaperTimer = null;
    state.analysisPaperRequest += 1;
  }
  if (view === "library") {
    loadPapers($("#library-search").value);
    if (state.paperInsightId) loadPaperInsights(state.paperInsightId, { quiet: true });
  }
  if (view === "analysis") loadAnalysisPaperList();
  if (view === "runs") loadRuns();
  if (view === "agents") loadAgentTrace();
  if (view === "system") loadSystemCare();
}

function systemCheckCard(title, check) {
  const ok = Boolean(check?.ok);
  const detail = check?.error || check?.message || (check?.installed_models ? `Selected: ${check.selected_model || "none"} · ${check.installed_models.length} model(s) found` : check?.state || "Check completed");
  return `<article class="system-check-card"><div class="system-check-top"><strong>${escapeHTML(title)}</strong><span class="system-pill ${ok ? "ok" : "attention"}">${ok ? "READY" : "CHECK"}</span></div><p>${escapeHTML(detail)}</p></article>`;
}
function renderSystemCare(data) {
  state.systemStatus = data;
  const checks = data.checks || {};
  const allGood = ["source", "app_startup", "database"].every((key) => checks[key]?.ok);
  const modelNote = checks.local_model?.ok ? "Local model is available" : "Local model is offline; research search and system checks still work";
  const hasChecks = Object.keys(checks).length > 0;
  $("#system-summary").innerHTML = `${hasChecks ? `<div class="system-health-banner ${allGood ? "healthy" : "attention"}"><span class="system-health-icon">${allGood ? "✓" : "!"}</span><div><strong>${allGood ? "ResearchOS is healthy" : "ResearchOS needs attention"}</strong><span>${escapeHTML(modelNote)} · Checked ${escapeHTML(dateLabel(checks.checked_at))}</span></div></div><div class="system-check-grid">${systemCheckCard("Source files", checks.source)}${systemCheckCard("App startup", checks.app_startup)}${systemCheckCard("Research database", checks.database)}${systemCheckCard("Local model", checks.local_model)}</div>` : ""}`;
  const incidents = data.incidents || [];
  $("#system-incidents").innerHTML = incidents.length ? incidents.map((item) => `<article class="system-log-row"><div class="system-log-top"><strong>${escapeHTML(item.source || "System incident")}</strong><time>${escapeHTML(dateLabel(item.created_at))}</time></div><span>${escapeHTML(item.error_type || "Error")}</span><p>${escapeHTML(item.message || "")}</p></article>`).join("") : `<div class="system-empty">No incidents recorded.</div>`;
  const reports = data.reports || [];
  $("#system-reports").innerHTML = reports.length ? reports.map((item) => `<article class="system-log-row"><div class="system-log-top"><strong>${escapeHTML(item.trigger || "System review")}</strong><span class="system-pill ${item.status === "healthy" || item.status === "auto_repaired" ? "ok" : "attention"}">${escapeHTML(String(item.status || "review").replaceAll("_", " ").toUpperCase())}</span></div><time>${escapeHTML(dateLabel(item.created_at))}</time>${item.diagnosis ? `<p>${escapeHTML(item.diagnosis)}</p>` : ""}${(item.repairs || []).map((repair) => `<p class="system-log-repair">${escapeHTML(repair.message || (repair.files || []).join(", "))}</p>`).join("")}${(item.improvements || []).slice(0, 3).map((idea) => `<p class="system-log-idea"><strong>${escapeHTML(idea.title || "Improvement")}</strong> · ${escapeHTML(idea.benefit || idea.reason || "")}</p>`).join("")}</article>`).join("") : `<div class="system-empty">No engineer reviews yet.</div>`;
}
async function loadSystemCare() {
  $("#system-summary").innerHTML = `<div class="empty-state compact-empty"><div class="empty-icon">◌</div><strong>Checking your lab</strong><span>Running source, startup, database, and model checks.</span></div>`;
  try { renderSystemCare(await api("/api/system/status")); }
  catch (error) { $("#system-summary").innerHTML = `<div class="system-health-banner attention"><span class="system-health-icon">!</span><div><strong>Could not reach System Care</strong><span>${escapeHTML(error.message)}</span></div></div>`; }
}

function statusLabel(status) {
  return ({ queued: "QUEUED", running: "IN PROGRESS", completed: "COMPLETE", partial: "PARTIAL RESULT", failed: "NEEDS ATTENTION" })[status] || String(status || "UNKNOWN").toUpperCase();
}
async function openInsightReportChat(id) {
  const loaded = await loadRunDetail(id);
  if (loaded === false) return;
  if (state.view !== "detail" || state.detailRunId !== id) return;
  $("#run-chat-root").scrollIntoView({ behavior: "smooth", block: "start" });
  setTimeout(() => {
    if (state.view === "detail" && state.detailRunId === id) $("#report-chat-form textarea")?.focus();
  }, 350);
}
function runRow(run) {
  const active = run.status === "running" || run.status === "queued";
  return `<div class="run-row" data-run="${escapeHTML(run.id)}" role="button" tabindex="0">
    <div class="run-icon">${active ? "◌" : "✳"}</div><div class="run-main"><div class="run-name">${escapeHTML(run.question)}</div>
    <div class="run-meta">${escapeHTML(run.project_name || "Research project")} · ${escapeHTML(dateLabel(run.created_at))}</div></div>
    <div class="run-right"><span class="status-chip ${escapeHTML(run.status)}">${escapeHTML(statusLabel(run.status))}</span><span class="run-papers">${Number(run.paper_count || 0)} papers</span></div></div>`;
}
function bindRunRows(root = document) {
  $$("[data-run]", root).forEach((row) => {
    const open = () => loadRunDetail(row.dataset.run);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  });
}
async function loadDashboard() {
  try {
    const data = await api("/api/dashboard");
    $("#metric-projects").textContent = data.project_count;
    $("#metric-papers").textContent = data.paper_count;
    $("#metric-runs").textContent = data.run_count;
    $("#metric-active").textContent = data.active_runs;
    $("#nav-paper-count").textContent = data.paper_count;
    $("#active-run-badge").textContent = data.active_runs ? "WORKING" : "READY";
    const html = data.recent_runs.length ? data.recent_runs.map(runRow).join("") : `<div class="empty-state compact-empty"><div class="empty-icon">✳</div><strong>Your next good question starts here</strong><span>Start a research run to see your team's work.</span></div>`;
    if ($("#recent-runs").innerHTML !== html) { $("#recent-runs").innerHTML = html; bindRunRows($("#recent-runs")); }
  } catch (error) {
    toast(`Could not load the local workspace: ${error.message}`, "error");
  }
}
async function loadProjects() {
  try {
    state.projects = await api("/api/projects");
    if (!state.projectId || !state.projects.some((project) => project.id === state.projectId)) state.projectId = state.projects[0]?.id || null;
    const listHTML = state.projects.map((project) => `<button class="project-link ${project.id === state.projectId ? "selected" : ""}" data-project="${escapeHTML(project.id)}" title="${escapeHTML(project.name)}">${escapeHTML(project.name)}</button>`).join("");
    if ($("#project-list").innerHTML !== listHTML) $("#project-list").innerHTML = listHTML;
    const select = $("#project-select");
    const selectHTML = state.projects.map((project) => `<option value="${escapeHTML(project.id)}">${escapeHTML(project.name)}</option>`).join("");
    if (select.innerHTML !== selectHTML) select.innerHTML = selectHTML;
    if (state.projectId) select.value = state.projectId;
    if (state.view === "project" && !state.projects.some((project) => project.id === state.projectId)) switchView("home");
  } catch (error) { console.error("Project list unavailable", error); }
}
async function openProject(id) {
  const project = state.projects.find((item) => item.id === id);
  if (!project) return;
  state.projectId = id;
  $("#project-list").querySelectorAll("[data-project]").forEach((button) => button.classList.toggle("selected", button.dataset.project === id));
  $("#project-select").value = id;
  $("#project-page-title").innerHTML = `${escapeHTML(project.name)}<span class="heading-period">.</span>`;
  $("#project-page-topic").textContent = project.topic || "Research notes and runs in this workspace.";
  $("#project-runs").innerHTML = `<div class="empty-state compact-empty"><div class="empty-icon">◌</div><strong>Loading project activity</strong></div>`;
  switchView("project");
  await loadProjectRuns(id);
}
async function loadProjectRuns(projectId) {
  const root = $("#project-runs");
  try {
    const allRuns = await api("/api/runs?limit=50");
    if (state.projectId !== projectId || state.view !== "project") return;
    const runs = allRuns.filter((run) => run.project_id === projectId);
    $("#project-run-count").textContent = runs.length;
    const html = runs.length ? runs.map(runRow).join("") : `<div class="empty-state compact-empty"><div class="empty-icon">✳</div><strong>No research runs yet</strong><span>Start an investigation to add it to this project.</span></div>`;
    if (root.innerHTML !== html) { root.innerHTML = html; bindRunRows(root); }
  } catch (error) {
    if (state.projectId === projectId && state.view === "project") root.innerHTML = `<div class="empty-state compact-empty"><strong>Could not load project activity</strong><span>${escapeHTML(error.message)}</span></div>`;
  }
}
async function loadModel() {
  try {
    const result = await api("/api/model");
    const wasConnected = state.modelConnected;
    state.modelRuntime = result.runtime || "ollama";
    state.modelConnected = result.connected && result.models.length > 0;
    $("#model-runtime").value = state.modelRuntime;
    $("#runtime-url").value = result.base_url || "http://127.0.0.1:11434/v1";
    $("#runtime-status").textContent = `Connected to ${state.modelRuntime}${result.models.length ? ` · ${result.models.length} model${result.models.length === 1 ? "" : "s"} ready` : " · no models installed yet"}.`;
    $("#model-label").textContent = state.modelConnected ? `${state.modelRuntime} · ${result.selected_model || result.models[0]}` : `${state.modelRuntime} connected`;
    $("#model-description").textContent = state.modelConnected ? "The local model loads when a research run starts." : `Add a model to ${state.modelRuntime} to enable local analysis.`;
    fillModelOptions(result);
    if (wasConnected !== state.modelConnected && state.reportChat.ready) renderReportChat();
  } catch {
    const wasConnected = state.modelConnected;
    state.modelConnected = false;
    if (wasConnected && state.reportChat.ready) renderReportChat();
    $("#model-label").textContent = "Local model offline";
    $("#model-description").textContent = "Web search still works. Start Ollama for local agent analysis.";
    $("#runtime-status").textContent = "Local model server is offline. Start Ollama or llama.cpp, then connect.";
    $("#model-picker-status").textContent = "Could not reach the local model server. Start it and refresh this list.";
    $("#model-select").innerHTML = "<option value=\"\">No local models found</option>";
    $("#model-select").disabled = true;
    $("#model-form").querySelector('[type="submit"]').disabled = true;
  }
}
function fillModelOptions(result) {
  const select = $("#model-select");
  const models = result.models || [];
  state.modelDetails = result.model_details || models.map((name) => ({ name, size_bytes: null }));
  select.innerHTML = models.map((model) => {
    const details = state.modelDetails.find((item) => item.name === model);
    const size = details?.size_bytes ? ` · ${prettyBytes(details.size_bytes)}` : "";
    return `<option value="${escapeHTML(model)}">${escapeHTML(model)}${size}</option>`;
  }).join("");
  select.disabled = models.length === 0;
  $("#model-form").querySelector('[type="submit"]').disabled = models.length === 0;
  if (result.selected_model) select.value = result.selected_model;
  $("#model-picker-status").textContent = models.length
    ? `${models.length} local model${models.length === 1 ? "" : "s"} available. The selected model is saved for future runs.`
    : "The local server is connected but has no models installed. Install a model in Ollama, then refresh.";
  updateSelectedModelMemory();
}
function updateSelectedModelMemory() {
  const selected = $("#model-select").value;
  const size = state.modelDetails.find((item) => item.name === selected)?.size_bytes;
  if (!selected || !size) {
    $("#model-picker-status").textContent = selected
      ? `${selected} is selected. This runtime does not report model size.`
      : "Model chat requests go to the local server you connect.";
    renderModelRoleMemory();
    return;
  }
  const estimated = Number(size) / (1024 ** 3) + 2;
  const estimate = `Roughly ${estimated.toFixed(0)} GB or more with a short context; actual use varies.`;
  $("#model-picker-status").textContent = estimated >= 10
      ? `${selected} · ${prettyBytes(size)} weights. ${estimate} This may be tight on this device.`
    : `${selected} · ${prettyBytes(size)} weights. ${estimate}`;
  renderModelRoleMemory();
}
async function refreshModelOptions() {
  $("#model-picker-status").textContent = "Checking the local model server…";
  try {
    const result = await api("/api/model");
    state.modelRuntime = result.runtime || state.modelRuntime;
    state.modelConnected = result.connected && result.models.length > 0;
    $("#model-runtime").value = state.modelRuntime;
    $("#runtime-url").value = result.base_url || $("#runtime-url").value;
    $("#runtime-status").textContent = `Connected to ${state.modelRuntime} · ${result.models.length} model${result.models.length === 1 ? "" : "s"} ready.`;
    fillModelOptions(result);
    await loadModelRoleSettings();
    await loadModelCatalog();
  } catch (error) {
    $("#model-picker-status").textContent = `Could not load models: ${error.message}`;
  }
}
function renderModelCatalog(data) {
  const root = $("#model-catalog");
  const downloads = data.downloads || {};
  const activeDownload = Object.values(downloads).some((entry) => entry.status === "downloading");
  $("#ollama-custom-pull").disabled = !data.ollama_available || activeDownload;
  $("#model-catalog-status").textContent = data.ollama_available
    ? "Recommended compact models. Downloads can take time and use disk space."
    : "Connect to Ollama to download from its library. Your llama.cpp server can still use installed models.";
  root.innerHTML = (data.models || []).map((item) => {
    const progress = downloads[item.name];
    const downloading = progress?.status === "downloading";
    const percent = progress?.total ? Math.min(100, Math.floor(100 * Number(progress.completed || 0) / Number(progress.total))) : 0;
    const button = item.installed ? `<button class="secondary-button" type="button" disabled>Installed</button>`
      : `<button class="secondary-button" type="button" data-install-model="${escapeHTML(item.name)}" ${!data.ollama_available || downloading || Object.values(downloads).some((entry) => entry.status === "downloading") ? "disabled" : ""}>${downloading ? "Downloading…" : progress?.status === "complete" ? "Downloaded" : "Download"}</button>`;
    const transfer = downloading || progress?.status === "complete" || progress?.status === "error"
      ? `<div class="model-download-progress"><span style="width:${progress?.status === "complete" ? 100 : percent}%"></span></div><span class="model-download-status">${escapeHTML(progress.message || progress.status)}${progress?.total ? ` · ${percent}%` : ""}</span>` : "";
    return `<article class="model-catalog-card"><div class="model-catalog-copy"><strong>${escapeHTML(item.name)}</strong><span>${escapeHTML(item.description)}</span><div class="model-catalog-meta"><span>${escapeHTML(item.size)}</span><a href="${escapeHTML(item.url)}" target="_blank" rel="noopener noreferrer">Open Ollama page ↗</a></div></div>${button}${transfer}</article>`;
  }).join("");
}
async function loadModelCatalog() {
  try { renderModelCatalog(await api("/api/models/catalog")); }
  catch (error) { $("#model-catalog-status").textContent = `Could not load Ollama catalog: ${error.message}`; }
}
function activateModelTab(tab) {
  const isHF = tab === "huggingface";
  $$("[data-model-tab]").forEach((button) => {
    const active = button.dataset.modelTab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("#ollama-models-panel").hidden = isHF;
  $("#huggingface-models-panel").hidden = !isHF;
}
function prettyBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "Size unavailable";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = bytes, index = 0;
  while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index++; }
  return `${amount.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}
async function searchHuggingFace(query) {
  $("#hf-results").innerHTML = `<p class="model-catalog-status">Searching public Hugging Face models…</p>`;
  $("#hf-files").innerHTML = "";
  try {
    const result = await api(`/api/models/huggingface/search?query=${encodeURIComponent(query)}`);
    $("#hf-results").innerHTML = result.models.length ? result.models.map((model) => `<article class="model-catalog-card hf-repo-card"><div class="model-catalog-copy"><strong>${escapeHTML(model.id)}</strong><span>${Number(model.downloads || 0).toLocaleString()} downloads · Public GGUF repository</span></div><button class="secondary-button" type="button" data-hf-repo="${escapeHTML(model.id)}">Choose file</button></article>`).join("") : `<p class="model-catalog-status">No public GGUF repositories found. Try a shorter model name.</p>`;
  } catch (error) {
    $("#hf-results").innerHTML = `<p class="model-catalog-status">${escapeHTML(error.message)}</p>`;
  }
}
async function showHuggingFaceFiles(repo) {
  state.hfRepo = repo;
  $("#hf-files").innerHTML = `<p class="model-catalog-status">Loading GGUF files from ${escapeHTML(repo)}…</p>`;
  try {
    const result = await api(`/api/models/huggingface/${repo.split("/").map(encodeURIComponent).join("/")}/files`);
    $("#hf-files").innerHTML = `<div class="hf-file-heading"><strong>${escapeHTML(repo)}</strong><span>Choose one GGUF file to download</span></div>${result.files.length ? result.files.map((file) => {
      const weightGB = Number(file.size || 0) / (1024 ** 3);
      const estimate = file.size ? `Approx. ${Math.ceil(weightGB + 2)} GB+ memory with a short context` : "Memory estimate unavailable";
      const warning = weightGB >= 8 ? " · May be tight on 16 GB" : "";
      return `<article class="model-catalog-card"><div class="model-catalog-copy"><strong>${escapeHTML(file.filename)}</strong><span>${escapeHTML(prettyBytes(file.size))} · ${escapeHTML(estimate)}${warning}</span></div><button class="secondary-button" type="button" data-hf-download="${escapeHTML(file.filename)}">Download</button></article>`;
    }).join("") : `<p class="model-catalog-status">This repository has no GGUF files.</p>`}`;
  } catch (error) {
    $("#hf-files").innerHTML = `<p class="model-catalog-status">${escapeHTML(error.message)}</p>`;
  }
}
async function refreshHuggingFaceDownloads() {
  try {
    const data = await api("/api/models/huggingface/downloads");
    const jobs = Object.values(data.downloads || {});
    $("#hf-downloads").innerHTML = jobs.map((job) => {
      const percent = job.total ? Math.min(100, Math.floor(Number(job.completed || 0) * 100 / Number(job.total))) : 0;
      return `<article class="hf-job"><div><strong>${escapeHTML(job.filename)}</strong><span>${escapeHTML(job.message)}${job.total ? ` · ${percent}%` : ""}</span></div><div class="model-download-progress"><span style="width:${job.status === "complete" ? 100 : percent}%"></span></div>${job.status === "complete" ? `<span class="hf-job-path">Saved on this device: ${escapeHTML(job.path)}</span><span class="hf-job-path">Use it with llama.cpp by pointing llama-server at this GGUF file.</span>` : ""}</article>`;
    }).join("");
    if (jobs.some((job) => job.status === "downloading") && !state.hfDownloadTimer) {
      state.hfDownloadTimer = setInterval(refreshHuggingFaceDownloads, 1200);
    } else if (!jobs.some((job) => job.status === "downloading") && state.hfDownloadTimer) {
      clearInterval(state.hfDownloadTimer); state.hfDownloadTimer = null;
    }
    for (const job of jobs.filter((item) => item.status === "complete" && !item.notified)) {
      job.notified = true; toast(`${job.filename} downloaded to this device.`);
    }
  } catch (error) {
    $("#hf-downloads").innerHTML = `<p class="model-catalog-status">Could not load download status: ${escapeHTML(error.message)}</p>`;
  }
}
async function connectModelRuntime() {
  const button = $("#runtime-connect");
  button.disabled = true; button.textContent = "Connecting…";
  const runtime = $("#model-runtime").value;
  const base_url = $("#runtime-url").value.trim();
  $("#runtime-status").textContent = `Checking ${runtime} at ${base_url}…`;
  try {
    const result = await api("/api/model/connection", { method: "POST", body: JSON.stringify({ runtime, base_url }) });
    state.modelRuntime = result.runtime;
    state.modelConnected = result.models.length > 0;
    fillModelOptions(result);
    if (state.reportChat.ready) renderReportChat();
    $("#runtime-status").textContent = `Connected to ${result.runtime} · ${result.models.length} model${result.models.length === 1 ? "" : "s"} ready.`;
    $("#model-label").textContent = result.models.length ? `${result.runtime} · ${result.selected_model}` : `${result.runtime} connected`;
    await loadModelCatalog();
    await loadModelRoleSettings();
    toast(`Connected to ${result.runtime} on this device.`);
  } catch (error) {
    $("#runtime-status").textContent = error.message;
    toast(error.message, "error");
  } finally { button.disabled = false; button.textContent = "Connect"; }
}
async function watchModelDownload(model) {
  while ($("#model-dialog").open) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    let result;
    try { result = await api("/api/models/catalog"); }
    catch (error) { $("#model-catalog-status").textContent = error.message; return; }
    renderModelCatalog(result);
    const progress = result.downloads?.[model];
    if (progress?.status === "complete") {
      await refreshModelOptions();
      await loadModelRoleSettings();
      toast(`${model} is installed. Select it above when you want to use it.`);
      return;
    }
    if (["error", "cancelled"].includes(progress?.status)) {
      toast(`Could not finish ${model}: ${progress.message}`, "error");
      return;
    }
    if (!progress) return;
  }
}
function formatAnalysisStatement(statement) {
  if (!statement || typeof statement.text !== "string") return "";
  const ids = new Set(statement.evidence_ids || []);
  return escapeHTML(statement.text).replace(/\[(F\d{3})\]/g, (label, id) => ids.has(id)
    ? `<a class="analysis-evidence-ref" href="#paper-evidence-${id}">${label}</a>` : label);
}
function paperCitation(paper = {}) {
  const authors = (paper.authors || []).filter(Boolean);
  const authorText = authors.length ? `${authors.slice(0, 8).join("; ")}${authors.length > 8 ? "; et al." : ""}` : "Author metadata unavailable";
  const parts = [`${authorText} (${paper.year || "year unavailable"}).`, `${paper.title || "Title unavailable"}.`];
  const journal = String(paper.journal || "").trim();
  if (journal) {
    let publication = journal;
    if (paper.volume) publication += `, ${paper.volume}`;
    if (paper.issue) publication += `(${paper.issue})`;
    if (paper.pages) publication += `, ${paper.pages}`;
    parts.push(`${publication}.`);
  }
  if (paper.doi) parts.push(`https://doi.org/${String(paper.doi).replace(/^https?:\/\/doi\.org\//i, "")}`);
  else if (paper.url) parts.push(String(paper.url));
  return parts.join(" ");
}
function bibtexEscape(value) {
  return String(value || "").replace(/([\\{}])/g, "\\$1").replace(/\s+/g, " ").trim();
}
function paperBibtex(paper = {}) {
  const author = (paper.authors || []).filter(Boolean).join(" and ");
  const keyBase = ((paper.authors || ["researchos"])[0] || "researchos").split(/[ ,]/)[0].replace(/[^A-Za-z0-9]/g, "") || "researchos";
  const year = paper.year || "nd";
  const slug = String(paper.title || "paper").split(/\s+/).slice(0, 3).join("").replace(/[^A-Za-z0-9]/g, "").slice(0, 18) || "paper";
  const fields = { author, title: paper.title, journal: paper.journal, publisher: paper.publisher, year: paper.year,
    volume: paper.volume, number: paper.issue, pages: paper.pages, doi: paper.doi, url: paper.url };
  const entries = Object.entries(fields).filter(([, value]) => value !== undefined && value !== null && String(value).trim())
    .map(([key, value]) => `  ${key} = {${bibtexEscape(value)}}`).join(",\n");
  return `@article{${keyBase}${year}${slug},\n${entries}\n}`;
}
function formatPaperAnswer(answer, evidenceIds = []) {
  const ids = new Set(evidenceIds || []);
  return escapeHTML(answer || "").replace(/\[(F\d{3})\]/g, (label, id) => ids.has(id)
    ? `<a class="analysis-evidence-ref" href="#paper-evidence-${id}">${label}</a>` : "")
    .replace(/\n{2,}/g, "</p><p>").replace(/\n/g, "<br>");
}
function renderPaperChat(analysis) {
  if (!analysis?.id) return "";
  if (state.paperChat.analysisId !== analysis.id) state.paperChat = { analysisId: analysis.id, messages: [], sending: false };
  const messages = state.paperChat.messages.map((message) => `<article class="paper-chat-message ${message.role}"><strong>${message.role === "user" ? "You" : "Grounded answer"}</strong>${message.role === "assistant" ? `<p>${formatPaperAnswer(message.answer, message.evidence_ids)}</p>` : `<p>${escapeHTML(message.text)}</p>`}</article>`).join("");
  return `<section class="paper-chat-panel" id="paper-analysis-chat"><div><span class="section-overline">ASK THIS PAPER</span><h4>Paper Q&amp;A</h4><p>Answers use only validated findings from this PDF. Citation IDs jump to the exact quote and page.</p></div><div class="paper-chat-messages" aria-live="polite">${messages || `<div class="paper-chat-empty">Ask about the method, dataset, experiment, result, or limitation.</div>`}${state.paperChat.sending ? `<div class="paper-chat-wait">Checking the paper's quoted evidence…</div>` : ""}</div><form class="paper-chat-form" data-paper-chat-form data-analysis-id="${escapeHTML(analysis.id)}"><input type="text" name="message" maxlength="4000" placeholder="Ask a question about this paper…" required ${state.paperChat.sending ? "disabled" : ""}/><button class="secondary-button" type="submit" ${state.paperChat.sending ? "disabled" : ""}>Ask</button></form></section>`;
}
function renderPaperAnalysis(analysis) {
  const result = analysis?.result || {};
  const evidence = Array.isArray(result.evidence) ? result.evidence : [];
  const paperId = analysis?.paper_id || result.paper?.id || "";
  const evidenceByCategory = new Map();
  for (const item of evidence) {
    const key = item.category || "other";
    evidenceByCategory.set(key, [...(evidenceByCategory.get(key) || []), item]);
  }
  const sections = (result.sections || []).map((section) => `<section class="paper-analysis-section"><h4>${escapeHTML(section.title || "Analysis")}</h4>${(section.items || []).map((item) => `<p>${formatAnalysisStatement(item)}</p>`).join("")}</section>`).join("");
  const evidenceHTML = [...evidenceByCategory.entries()].map(([category, items]) => `<details class="paper-evidence-group" ${["results", "metrics", "baselines"].includes(category) ? "open" : ""}><summary>${escapeHTML(category.replaceAll("_", " "))}<span>${items.length} source details</span></summary><div class="paper-evidence-list">${items.map((item) => { const page = Math.max(1, Number(item.page) || 1); const sourcePage = `/api/papers/${encodeURIComponent(paperId)}/file?inline=1#page=${page}`; return `<article class="paper-evidence-item" id="paper-evidence-${escapeHTML(item.id)}"><div><strong>${escapeHTML(item.id)} · PDF page ${Number(item.page) || "?"}</strong><span>${escapeHTML(item.detail || "")}</span><a class="paper-page-link" href="${escapeHTML(sourcePage)}" target="_blank" rel="noopener noreferrer">Open cited page ↗</a></div><blockquote>${escapeHTML(item.evidence_quote || "")}</blockquote></article>`; }).join("")}</div></details>`).join("");
  const sota = result.state_of_art || {};
  const coverage = result.coverage || {};
  const figures = Array.isArray(result.figures) ? result.figures : null;
  const figureCards = figures?.map((figure) => {
    const page = Math.max(1, Number(figure.page) || 1);
    const pdfPageUrl = `/api/papers/${encodeURIComponent(paperId)}/file?inline=1#page=${page}`;
    const caption = figure.caption
      ? `<p>${escapeHTML(figure.caption)}</p>`
      : `<p class="paper-figure-caption-missing">No figure caption was extracted from this page.</p>`;
    return `<article class="paper-figure-card"><a class="paper-figure-image-link" href="${escapeHTML(figure.url || "#")}" target="_blank" rel="noopener noreferrer" aria-label="Open full preview for PDF page ${page}"><img src="${escapeHTML(figure.url || "")}" alt="${escapeHTML(figure.kind || "Figure page")} from PDF page ${page}" loading="lazy" /></a><div class="paper-figure-meta"><strong>${escapeHTML(figure.kind || "Figure")} · PDF page ${page}</strong><a href="${escapeHTML(pdfPageUrl)}" target="_blank" rel="noopener noreferrer">Open original page ↗</a></div>${caption}</article>`;
  }).join("") || "";
  const figuresHTML = figures === null
    ? `<section class="paper-analysis-section paper-visuals-section"><h4>Visuals and diagrams</h4><p>This saved analysis predates page previews. Choose Analyze again to capture architecture, dataset, experiment, and results pages.</p></section>`
    : `<section class="paper-analysis-section paper-visuals-section"><h4>Visuals and diagrams</h4><p>Full-page previews preserve diagrams and charts. Captions come from the paper text; the local text model does not interpret image pixels.</p>${figureCards ? `<div class="paper-figure-grid">${figureCards}</div>` : `<p class="paper-figure-empty">No likely figure pages were found in the extracted text. Scanned pages without text may be missed; open the attached PDF to inspect the complete paper.</p>`}</section>`;
  return `<div class="paper-analysis-result"><div class="paper-analysis-summary"><span class="section-overline">DETAILED PDF ANALYSIS</span><p>${formatAnalysisStatement(result.summary)}</p><small>Every [F###] reference links to the exact validated quote below. “PDF page” means the page number in the uploaded file.</small></div>${sections}${figuresHTML}<section class="paper-sota-note"><strong>This paper's state-of-the-art claim</strong><p>${sota.paper_claim ? formatAnalysisStatement(sota.paper_claim) : "No paper-authored state-of-the-art claim was verified in the extracted text."}</p><p>${escapeHTML(sota.assessment || "A single paper cannot establish current state of the art; compare current studies using the same benchmark and protocol.")}</p></section>${result.not_reported_or_unclear?.length ? `<section class="paper-analysis-section"><h4>Not reported or unclear in the extracted pages</h4><ul>${result.not_reported_or_unclear.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul></section>` : ""}<div class="paper-analysis-coverage">${Number(coverage.validated_finding_count || evidence.length)} quoted findings · ${Number(coverage.pages_with_text || 0)} pages with text${coverage.text_truncated_at_upload ? " · PDF text was truncated at upload" : ""}</div><div class="paper-evidence-heading"><div><span class="section-overline">CHECK THE SOURCE</span><h4>Extracted findings and page quotes</h4></div></div>${evidenceHTML}${renderPaperChat(analysis)}${(result.limits || []).map((item) => `<p class="paper-analysis-limit">${escapeHTML(item)}</p>`).join("")}</div>`;
}
function renderPaperInsights(data) {
  const root = $("#paper-insight-panel");
  if (!data) { root.innerHTML = ""; return; }
  const paper = data.paper || {};
  const abstract = paper.abstract ? `<section class="paper-insight-section"><h4>Saved abstract or text</h4><p>${escapeHTML(paper.abstract)}</p></section>` : "";
  const metrics = (data.reported_metrics || []).map((metric) => `<article class="reported-metric-card"><div class="reported-metric-top"><h3>${escapeHTML(metric.metric || "Reported metric")}</h3><span>${escapeHTML(metric.reported_result || "Result not stated")}</span></div><p>${escapeHTML(metric.what_it_measures || "")}</p><blockquote>${escapeHTML(metric.evidence_quote || "")}</blockquote><span class="event-copy">${escapeHTML(metric.report_question || "Saved report")}</span></article>`).join("");
  const comparisons = (data.same_metric_saved_results || []).map((metric) => `<article class="paper-saved-claim"><div class="reported-metric-top"><h3>${escapeHTML(metric.metric || "Matching metric")}</h3><strong>${escapeHTML(metric.reported_result || "Result not stated")}</strong></div><p>${escapeHTML(metric.title || "Saved study")}${metric.year ? ` · ${escapeHTML(metric.year)}` : ""} · ${escapeHTML(metric.source || "source")}</p><blockquote>${escapeHTML(metric.evidence_quote || "")}</blockquote><span>${escapeHTML(metric.report_question || "Saved report")}</span></article>`).join("");
  const claims = (data.claims || []).slice(0, 16).map((claim) => `<article class="paper-saved-claim"><p>${escapeHTML(claim.text || "")}</p><blockquote>${escapeHTML(claim.evidence || "")}</blockquote><span>${escapeHTML(claim.location || "Source passage")} · ${escapeHTML(claim.question || "Prior report")}</span></article>`).join("");
  const reports = (data.prior_reports || []).map((report) => `<article class="paper-prior-report"><div><strong>${escapeHTML(report.question || "Research report")}</strong><p>${escapeHTML(report.executive_summary || "No report summary was saved.")}</p></div><button class="secondary-button" type="button" data-open-insight-report="${escapeHTML(report.id)}">Open report &amp; chat</button></article>`).join("");
  const latest = (data.analyses || [])[0];
  const citationTarget = paper.doi ? `https://doi.org/${String(paper.doi).replace(/^https?:\/\/doi\.org\//i, "")}` : (paper.url || "");
  const citationBox = `<section class="paper-citation-box"><div><span class="section-overline">CITATION &amp; PROVENANCE</span><h4>Suggested citation</h4></div><p>${escapeHTML(paperCitation(paper))}</p><div class="paper-citation-actions"><button type="button" class="secondary-button" data-copy-paper-citation>Copy citation</button><button type="button" class="secondary-button" data-copy-paper-bibtex>Copy BibTeX</button>${citationTarget ? `<a class="quiet-link" href="${escapeHTML(citationTarget)}" target="_blank" rel="noopener noreferrer">Open DOI/source ↗</a>` : ""}</div><small>Bibliographic details come from the saved record. In PDF analysis, [F###] links to a validated quotation and PDF page; verify the citation metadata against the publisher before submission.</small></section>`;
  const analysisActionLabel = latest && ["queued", "running"].includes(latest.status)
    ? "Open analysis in progress →" : "Open PDF analysis →";
  const candidateMetrics = (data.candidate_metrics || []).slice(0, 18).map((metric) => `<div class="paper-candidate-metric"><strong>${escapeHTML(metric.name || "Candidate metric")}</strong><span>${escapeHTML(metric.definition || "")}</span><small>Proposed in: ${escapeHTML(metric.report_question || "saved plan")}</small></div>`).join("");
  root.innerHTML = `<section class="detail-panel paper-insights-panel"><div class="paper-insights-heading"><div><span class="section-overline">ALREADY IN YOUR LIBRARY</span><h2>${escapeHTML(paper.title || "Saved paper")}</h2><p>${escapeHTML((paper.authors || []).join(", ") || "Author metadata unavailable")} · ${escapeHTML(paper.year || "Year unknown")}${paper.journal ? ` · ${escapeHTML(paper.journal)}` : ""} · ${escapeHTML(paper.source || "Saved source")}${paper.doi ? ` · DOI ${escapeHTML(paper.doi)}` : ""}</p></div><button type="button" class="quiet-link" data-close-paper-insights>Close ×</button></div>${citationBox}${abstract}<div class="paper-sota-note"><strong>Using these saved results</strong><p>Reported numbers below come from saved source quotes. Same-named metrics from other papers are shown as possible leads, not ranked: dataset, split, task, and evaluation protocol must match before calling a result SOTA.</p></div>${metrics ? `<section class="paper-insight-section"><h4>Results explicitly reported for this paper</h4><div class="reported-metric-grid">${metrics}</div></section>` : ""}${comparisons ? `<section class="paper-insight-section"><h4>Saved results with the same metric name</h4>${comparisons}</section>` : ""}${candidateMetrics ? `<section class="paper-insight-section"><h4>Metrics proposed in prior plans</h4><p>These are candidates, not results reported by the paper.</p>${candidateMetrics}</section>` : ""}${claims ? `<section class="paper-insight-section"><h4>Source-grounded findings in prior reports</h4>${claims}</section>` : ""}${reports ? `<section class="paper-insight-section"><h4>Previously included in ${reports.length} saved report${reports.length === 1 ? "" : "s"}</h4>${reports}</section>` : `<div class="paper-insight-empty">This source is saved, but no completed research report has analyzed it yet.</div>`}<section class="paper-analysis-launch"><div><span class="section-overline">DETAILED PDF REPORT</span><h3>Open the PDF analysis workspace</h3><p>The full report, page citations, figure previews, and paper Q&amp;A live in PDF Analysis.</p></div><button class="secondary-button" type="button" data-open-paper-analysis="${escapeHTML(paper.id)}">${analysisActionLabel}</button></section></section>`;
}
async function loadPaperInsights(id, { quiet = false } = {}) {
  if (state.view !== "library") return null;
  const request = ++state.paperInsightRequest;
  if (state.paperInsightId !== id) {
    state.paperInsightId = id; state.paperInsightData = null;
    if (state.paperInsightTimer) clearTimeout(state.paperInsightTimer);
    state.paperInsightTimer = null;
    if (!quiet) $("#paper-insight-panel").innerHTML = `<div class="detail-panel paper-insights-panel"><div class="paper-insight-empty">Loading saved paper details and previous results…</div></div>`;
  }
  try {
    const data = await api(`/api/papers/${encodeURIComponent(id)}/research`);
    if (state.paperInsightId !== id || request !== state.paperInsightRequest) return;
    state.paperInsightData = data;
    const scrollY = window.scrollY;
    renderPaperInsights(data);
    if (quiet) requestAnimationFrame(() => window.scrollTo({ top: scrollY, behavior: "instant" }));
    const latest = (data.analyses || [])[0];
    if (latest && ["queued", "running"].includes(latest.status)) {
      state.paperInsightTimer = setTimeout(() => loadPaperInsights(id, { quiet: true }), 2400);
    } else if (state.paperInsightTimer) {
      clearTimeout(state.paperInsightTimer); state.paperInsightTimer = null;
    }
    return data;
  } catch (error) {
    if (state.paperInsightId === id && request === state.paperInsightRequest) $("#paper-insight-panel").innerHTML = `<div class="detail-panel paper-insights-panel"><div class="paper-insight-empty">Could not load saved paper details: ${escapeHTML(error.message)}</div></div>`;
    return null;
  }
}
async function startPaperAnalysis(id, button) {
  if (button) { button.disabled = true; button.textContent = "Adding to local queue…"; }
  try {
    await api(`/api/papers/${encodeURIComponent(id)}/analyses`, { method: "POST", body: "{}" });
    toast("Paper Analysis was added to the local queue.");
    if (state.paperInsightId === id) await loadPaperInsights(id);
    if (state.analysisPaperId === id && state.view === "analysis") await loadAnalysisPaper(id);
  } catch (error) {
    toast(error.message, "error");
    if (state.paperInsightId === id) await loadPaperInsights(id);
    if (state.analysisPaperId === id && state.view === "analysis") await loadAnalysisPaper(id);
  }
}
async function loadPapers(query = "", request = ++state.paperSearchSequence) {
  const normalizedQuery = String(query || "").trim();
  try {
    const papers = await api(`/api/papers?limit=250&q=${encodeURIComponent(normalizedQuery)}`);
    if (request !== state.paperSearchSequence) return;
    $("#paper-list").setAttribute("aria-busy", "false");
    $("#library-total").textContent = papers.length;
    const paperWord = papers.length === 1 ? "paper" : "papers";
    $("#library-total-label").textContent = normalizedQuery ? `${paperWord} shown` : `${paperWord} saved`;
    if (state.paperInsightId && !papers.some((paper) => paper.id === state.paperInsightId)) {
      if (state.paperInsightTimer) clearTimeout(state.paperInsightTimer);
      state.paperInsightTimer = null; state.paperInsightId = null; state.paperInsightData = null;
      state.paperInsightRequest += 1;
      renderPaperInsights(null);
    }
    $("#paper-list").innerHTML = papers.length ? papers.map((paper) => {
      const target = paper.local_file ? `/api/papers/${encodeURIComponent(paper.id)}/file` : (paper.url || (paper.doi ? `https://doi.org/${paper.doi}` : "#"));
      return `<div class="paper-row">
      <div><a class="paper-title" href="${escapeHTML(target)}" target="_blank" rel="noopener noreferrer">${escapeHTML(paper.title)}</a>
      <div class="paper-authors">${escapeHTML((paper.authors || []).slice(0, 3).join(", ") || "Author metadata unavailable")}${(paper.authors || []).length > 3 ? " et al." : ""}</div><button class="paper-insights-toggle" type="button" data-paper-insights="${escapeHTML(paper.id)}" aria-controls="paper-insight-panel" aria-expanded="${state.paperInsightId === paper.id}">Saved details &amp; results</button></div>
      <span class="paper-year">${escapeHTML(paper.year || "—")}</span><span class="paper-source"><span class="source-badge">${escapeHTML(paper.source)}</span></span>
      <a class="external-link" href="${escapeHTML(target)}" target="_blank" rel="noopener noreferrer" aria-label="Open paper">${paper.local_file ? "↓" : "↗"}</a></div>`;
    }).join("") : `<div class="empty-state"><div class="empty-icon">▤</div><strong>${normalizedQuery ? "No matching papers" : "Your library is ready"}</strong><span>${normalizedQuery ? "Try a title, author, DOI, or keyword." : "Find papers to save a record, start a research run, or add a PDF."}</span></div>`;
  } catch (error) {
    if (request === state.paperSearchSequence) {
      $("#paper-list").setAttribute("aria-busy", "false");
      $("#library-total-label").textContent = "search unavailable";
      toast(`Could not load papers: ${error.message}`, "error");
    }
  }
}
function renderModelUsage(queue) {
  const active = queue?.active ? `Running ${queue.active}` : "Queue idle";
  const waiting = Number(queue?.waiting || 0);
  const usage = queue?.usage || {};
  const labels = [["research", "Research"], ["pdf_analysis", "PDF"], ["chat", "Chat"], ["paper_ranking", "Matching"]]
    .filter(([key]) => Number(usage[key]?.calls || 0) > 0)
    .map(([key, label]) => `${label} ${Number(usage[key].calls)}`);
  const calls = Object.values(usage).reduce((sum, row) => sum + Number(row?.calls || 0), 0);
  const tokens = Object.values(usage).reduce((sum, row) => sum + Number(row?.input_tokens || 0) + Number(row?.output_tokens || 0), 0);
  const useNote = calls ? ` · ${labels.join(" · ")} · ${tokens.toLocaleString()} tokens this session` : " · no model calls this session";
  $("#model-usage-status").textContent = `${active}${waiting ? ` · ${waiting} waiting` : ""}${useNote}`;
}
async function refreshModelUsage() {
  try { renderModelUsage((await api("/api/model/usage")).queue); }
  catch { /* Settings remain useful while the local model server is offline. */ }
}
function setRoleModelOptions(select, models, selected) {
  const previous = selected || "";
  select.innerHTML = `<option value="">Use shared default model</option>${models.map((name) => {
    const size = state.modelDetails.find((item) => item.name === name)?.size_bytes;
    const sizeLabel = size ? ` · ${prettyBytes(size)} weights · ~${Math.ceil(Number(size) / (1024 ** 3) + 2)} GB+ RAM` : "";
    return `<option value="${escapeHTML(name)}">${escapeHTML(name)}${sizeLabel}</option>`;
  }).join("")}`;
  if (previous && !models.includes(previous)) {
    select.insertAdjacentHTML("beforeend", `<option value="${escapeHTML(previous)}">${escapeHTML(previous)} · unavailable</option>`);
  }
  select.value = previous;
}
function renderModelRoleMemory() {
  const selected = ["research", "pdf", "chat"].map((role) => {
    const value = $(`#role-model-${role}`).value || $("#model-select").value;
    const details = state.modelDetails.find((item) => item.name === value);
    return details?.size_bytes ? { name: value, bytes: Number(details.size_bytes) } : null;
  }).filter(Boolean);
  const biggest = selected.sort((a, b) => b.bytes - a.bytes)[0];
  const note = $("#model-role-memory-note");
  if (!biggest) {
    note.classList.remove("warning");
    note.textContent = "Task models run one at a time. The connected runtime does not report enough size information for a memory estimate.";
    return;
  }
  const estimate = Math.ceil(biggest.bytes / (1024 ** 3) + 2);
  const warning = estimate >= 16;
  note.classList.toggle("warning", warning);
  note.textContent = warning
    ? `Largest model assigned: ${biggest.name} · about ${estimate} GB or more at short context. This may exceed this device's available memory.`
    : `Largest model assigned: ${biggest.name} · roughly ${estimate} GB or more at short context. Task models run one at a time; actual use varies.`;
}
async function loadModelRoleSettings() {
  try {
    const data = await api("/api/model/roles");
    state.modelRoles = data.roles || {};
    setRoleModelOptions($("#role-model-research"), data.models || [], state.modelRoles.research);
    setRoleModelOptions($("#role-model-pdf"), data.models || [], state.modelRoles.pdf_analysis);
    setRoleModelOptions($("#role-model-chat"), data.models || [], state.modelRoles.chat);
    renderModelRoleMemory();
    renderModelUsage(data.queue);
  } catch (error) {
    $("#model-usage-status").textContent = `Could not load task models: ${error.message}`;
  }
}
async function saveModelRoleSettings() {
  const button = $("#model-roles-save");
  button.disabled = true;
  try {
    const data = await api("/api/model/roles", { method: "POST", body: JSON.stringify({ roles: {
      research: $("#role-model-research").value,
      pdf_analysis: $("#role-model-pdf").value,
      chat: $("#role-model-chat").value,
    } }) });
    state.modelRoles = data.roles || {};
    $("#model-usage-status").textContent = "Task model choices saved. Local jobs run one at a time.";
    toast("Task models saved.");
  } catch (error) {
    $("#model-usage-status").textContent = error.message;
    toast(error.message, "error");
  } finally { button.disabled = false; }
}
function renderSpecter2Status(data) {
  state.specter2Status = data;
  const setup = $("#specter2-setup");
  const enabled = $("#specter2-enabled");
  const badge = $("#specter2-badge");
  const status = $("#specter2-status");
  const progress = $("#specter2-progress");
  const active = ["installing", "downloading"].includes(data.status);
  badge.className = `system-pill ${data.ready ? "ok" : active ? "attention" : "attention"}`;
  badge.textContent = data.ready ? (data.enabled ? "ENABLED" : "READY") : active ? "SETTING UP" : "OPTIONAL";
  enabled.checked = Boolean(data.enabled);
  enabled.disabled = !data.ready;
  setup.disabled = active || data.ready;
  setup.textContent = data.ready ? "SPECTER2 ready" : active ? "Setting up…" : data.status === "error" ? "Retry setup" : "Set up SPECTER2";
  status.textContent = data.message || (data.ready
    ? `Ready for local semantic ranking${data.device ? ` · ${data.device.toUpperCase()}` : ""}.`
    : data.dependencies_ready
      ? "Python runtime is installed; model weights still need to be downloaded."
      : "Optional model is not installed. Setup installs PyTorch, downloads about 450 MB of model weights, and keeps them on this device.");
  progress.hidden = !active;
  progress.classList.toggle("indeterminate", data.status === "downloading");
  progress.querySelector("span").style.width = `${Math.max(8, Number(data.progress || 0))}%`;
  renderModelUsage(data.queue);
}
async function refreshSpecter2Status() {
  try {
    const data = await api("/api/paper-ranker/status");
    renderSpecter2Status(data);
    const active = ["installing", "downloading"].includes(data.status);
    if (active && !state.specter2Timer) state.specter2Timer = setInterval(refreshSpecter2Status, 1500);
    if (!active && state.specter2Timer) { clearInterval(state.specter2Timer); state.specter2Timer = null; }
  } catch (error) { $("#specter2-status").textContent = `Could not read SPECTER2 status: ${error.message}`; }
}
async function startSpecter2Setup() {
  const button = $("#specter2-setup");
  button.disabled = true;
  try {
    await api("/api/paper-ranker/setup", { method: "POST", body: "{}" });
    await refreshSpecter2Status();
  } catch (error) {
    $("#specter2-status").textContent = error.message;
    button.disabled = false;
    toast(error.message, "error");
  }
}
async function setSpecter2Enabled(enabled) {
  const toggle = $("#specter2-enabled");
  toggle.disabled = true;
  try {
    await api("/api/paper-ranker/settings", { method: "POST", body: JSON.stringify({ enabled }) });
    await refreshSpecter2Status();
    toast(enabled ? "SPECTER2 ranking enabled for paper search and research runs." : "SPECTER2 ranking disabled.");
  } catch (error) {
    toggle.checked = !enabled;
    $("#specter2-status").textContent = error.message;
  } finally { toggle.disabled = !state.specter2Status?.ready; }
}
function openModelSettings() {
  if (!$("#model-dialog").open) $("#model-dialog").showModal();
  loadModelCatalog();
  loadModelRoleSettings();
  refreshSpecter2Status();
  if (!state.modelUsageTimer) state.modelUsageTimer = setInterval(() => {
    if ($("#model-dialog").open) refreshModelUsage();
  }, 2500);
}
function renderDiscoveryResults(papers) {
  const root = $("#discovery-results");
  root.setAttribute("aria-busy", "false");
  root.innerHTML = papers.length ? papers.map((paper, index) => {
    const sources = (paper.sources || [paper.source]).filter(Boolean).map((name) => `<span class="source-badge">${escapeHTML(name)}</span>`).join(" ");
    const authors = (paper.authors || []).slice(0, 5).join(", ") + ((paper.authors || []).length > 5 ? " et al." : "");
    const abstract = paper.abstract ? `<p class="discovery-abstract">${escapeHTML(paper.abstract.length > 520 ? `${paper.abstract.slice(0, 520).trimEnd()}…` : paper.abstract)}</p>` : `<p class="discovery-abstract muted">No abstract was returned by the index.</p>`;
    const target = paper.doi ? `https://doi.org/${String(paper.doi).replace(/^https?:\/\/doi\.org\//i, "")}` : (paper.url || "");
    const saved = paper.saved_paper_id ? `<section class="discovery-saved-info"><div><strong>Already in your library</strong><span>${Number(paper.saved_report_count || 0)} prior report${Number(paper.saved_report_count || 0) === 1 ? "" : "s"} · ${Number(paper.saved_metric_count || 0)} source-reported metric${Number(paper.saved_metric_count || 0) === 1 ? "" : "s"}${paper.saved_local_pdf ? " · PDF attached" : ""}${paper.saved_analysis_status ? ` · PDF analysis ${escapeHTML(paper.saved_analysis_status)}` : ""}</span></div><p>Open the saved details to inspect reported results, PDF quotes, and paper-specific analysis with source links.</p><button class="secondary-button" type="button" data-discovery-open="${escapeHTML(paper.saved_paper_id)}">Open saved details and results</button></section>` : "";
    const sourceId = paper.source_ids?.[paper.source] || paper.source_id || "";
    const semanticRank = paper.semantic_rank ? `<span class="semantic-rank">SPECTER2 match #${Number(paper.semantic_rank)}</span>` : "";
    return `<article class="discovery-card"><div class="discovery-card-head"><div>${sources} ${semanticRank}</div><span>${paper.year ? escapeHTML(paper.year) : "Year unavailable"}</span></div><h2>${target ? `<a href="${escapeHTML(target)}" target="_blank" rel="noopener noreferrer">${escapeHTML(paper.title || "Untitled paper")} ↗</a>` : escapeHTML(paper.title || "Untitled paper")}</h2><div class="discovery-citation-line">${escapeHTML(authors || "Author metadata unavailable")}${paper.journal ? ` · ${escapeHTML(paper.journal)}` : ""}${paper.doi ? ` · DOI ${escapeHTML(paper.doi)}` : ""}</div>${abstract}${saved}<div class="discovery-card-footer">${paper.open_access_url ? `<a class="quiet-link" href="${escapeHTML(paper.open_access_url)}" target="_blank" rel="noopener noreferrer">Open access full text ↗</a>` : `<span class="discovery-index-note">Indexed record · full text may require publisher access</span>`}${paper.saved_paper_id ? `<span class="saved-paper-chip">✓ Already saved</span>` : `<button class="secondary-button" type="button" data-discovery-save="${index}" data-source="${escapeHTML(paper.source || "")}" data-source-id="${escapeHTML(sourceId)}">Save to library</button>`}</div></article>`;
  }).join("") : `<div class="empty-state"><div class="empty-icon">⌕</div><strong>No papers returned</strong><span>Try an exact title, DOI, author, or a broader research phrase.</span></div>`;
}
async function runPaperDiscovery(query = $("#discovery-query").value) {
  const normalized = String(query || "").trim();
  if (normalized.length < 2) { $("#discovery-query").focus(); return; }
  const request = ++state.paperDiscoverySequence;
  const limit = Number($("#discovery-limit").value) || 50;
  $("#discovery-results").setAttribute("aria-busy", "true");
  $("#discovery-results").innerHTML = `<div class="empty-state"><div class="empty-icon">◌</div><strong>Searching trusted indexes…</strong><span>Crossref, Europe PMC, and OpenAlex are being queried in parallel.</span></div>`;
  $("#discovery-status").textContent = `Searching up to ${limit} records in each trusted index. Results will stay temporary until saved.`;
  try {
    const response = await api(`/api/paper-search?q=${encodeURIComponent(normalized)}&per_source=${limit}`);
    if (request !== state.paperDiscoverySequence) return;
    state.paperDiscoveryResults = response.papers || [];
    renderDiscoveryResults(state.paperDiscoveryResults);
    const errorSummary = (response.errors || []).join(" · ");
    const rankingNote = response.ranking?.method === "specter2"
      ? " Ranked locally by SPECTER2 semantic similarity; this is an ordering score, not a probability."
      : response.ranking?.fallback ? ` ${response.ranking.fallback}` : " Results use index and publication-date ordering.";
    $("#discovery-status").textContent = `${state.paperDiscoveryResults.length} unique papers found across ${response.sources.join(", ")}.${errorSummary ? ` Some indexes did not respond: ${errorSummary}` : " All three trusted indexes responded."}${rankingNote} Unselected hits are not stored.`;
  } catch (error) {
    if (request === state.paperDiscoverySequence) {
      $("#discovery-results").setAttribute("aria-busy", "false");
      $("#discovery-status").textContent = `Paper search could not connect: ${error.message}`;
      $("#discovery-results").innerHTML = `<div class="empty-state"><div class="empty-icon">!</div><strong>Search unavailable</strong><span>Check the ResearchOS server and internet connection, then try again.</span></div>`;
    }
  }
}
async function openPaperDetailsInLibrary(paperId) {
  switchView("library");
  await loadPaperInsights(paperId);
  requestAnimationFrame(() => $("#paper-insight-panel").scrollIntoView({ behavior: "smooth", block: "start" }));
}
async function loadAnalysisPaperList() {
  const root = $("#analysis-paper-list");
  root.setAttribute("aria-busy", "true");
  try {
    const papers = await api("/api/papers?limit=250");
    state.analysisPapers = papers.filter((paper) => paper.local_file);
    root.setAttribute("aria-busy", "false");
    renderAnalysisPaperList();
    if (!state.analysisPapers.length) {
      state.analysisPaperId = null;
      state.analysisPaperData = null;
      $("#analysis-paper-detail").innerHTML = `<div class="empty-state analysis-detail-empty"><div class="empty-icon">◈</div><strong>No PDF selected</strong><span>Add a PDF to start a detailed, source-linked analysis.</span></div>`;
      return;
    }
    if (!state.analysisPapers.some((paper) => paper.id === state.analysisPaperId)) state.analysisPaperId = state.analysisPapers[0].id;
    await loadAnalysisPaper(state.analysisPaperId);
  } catch (error) {
    root.setAttribute("aria-busy", "false");
    root.innerHTML = `<div class="empty-state"><div class="empty-icon">!</div><strong>Could not load local PDFs</strong><span>${escapeHTML(error.message)}</span></div>`;
  }
}
function renderAnalysisPaperList() {
  const root = $("#analysis-paper-list");
  if (!state.analysisPapers.length) {
    root.innerHTML = `<div class="empty-state compact-empty"><div class="empty-icon">◈</div><strong>No PDFs attached yet</strong><span>Add a paper PDF. It will stay on this device.</span></div>`;
    return;
  }
  root.innerHTML = state.analysisPapers.map((paper) => `<button type="button" class="analysis-paper-row ${state.analysisPaperId === paper.id ? "selected" : ""}" data-select-analysis-paper="${escapeHTML(paper.id)}" aria-current="${state.analysisPaperId === paper.id ? "true" : "false"}"><span class="analysis-paper-icon">PDF</span><span class="analysis-paper-copy"><strong>${escapeHTML(paper.title || paper.local_filename || "Local PDF")}</strong><span>${escapeHTML(paper.local_filename || "PDF attached")} · ${Number(paper.page_count || 0)} pages${paper.year ? ` · ${escapeHTML(paper.year)}` : ""}</span></span><span class="analysis-paper-chevron">›</span></button>`).join("");
}
async function openPaperAnalysis(paperId) {
  state.analysisPaperId = paperId;
  switchView("analysis");
  requestAnimationFrame(() => $("#analysis-paper-detail")?.scrollIntoView({ behavior: "smooth", block: "start" }));
}
async function loadAnalysisPaper(paperId, { quiet = false } = {}) {
  if (!paperId || state.view !== "analysis") return;
  const request = ++state.analysisPaperRequest;
  if (state.analysisPaperTimer) { clearTimeout(state.analysisPaperTimer); state.analysisPaperTimer = null; }
  const root = $("#analysis-paper-detail");
  if (!quiet) root.innerHTML = `<div class="empty-state compact-empty"><div class="empty-icon">◌</div><strong>Opening paper analysis</strong><span>Loading the saved PDF, analysis status, and page evidence.</span></div>`;
  try {
    const data = await api(`/api/papers/${encodeURIComponent(paperId)}/research`);
    if (request !== state.analysisPaperRequest || state.analysisPaperId !== paperId || state.view !== "analysis") return;
    state.analysisPaperData = data;
    renderAnalysisPaperDetail(data);
    const latest = (data.analyses || [])[0];
    if (latest && ["queued", "running"].includes(latest.status)) {
      state.analysisPaperTimer = setTimeout(() => loadAnalysisPaper(paperId, { quiet: true }), 2400);
    }
  } catch (error) {
    if (request === state.analysisPaperRequest && state.analysisPaperId === paperId && state.view === "analysis") {
      root.innerHTML = `<div class="empty-state compact-empty"><div class="empty-icon">!</div><strong>Could not load PDF analysis</strong><span>${escapeHTML(error.message)}</span></div>`;
    }
  }
}
function renderAnalysisPaperDetail(data) {
  const root = $("#analysis-paper-detail");
  const paper = data.paper || {};
  const latest = (data.analyses || [])[0];
  const analysisActive = latest && ["queued", "running"].includes(latest.status);
  const analysisStatus = analysisActive
    ? `<div class="paper-analysis-progress"><strong>${latest.status === "queued" ? "Waiting for the local model" : "Analyzing your PDF"}</strong><span>${escapeHTML(latest.stage || "queued")} · ${Number(latest.progress || 0)}%</span><div class="model-download-progress"><span style="width:${Number(latest.progress || 2)}%"></span></div></div>`
    : latest?.status === "failed" ? `<div class="paper-analysis-error" role="status">Previous attempt stopped: ${escapeHTML(latest.error || "Analysis failed. Check the local model and try again.")}</div>` : "";
  const citationTarget = paper.doi ? `https://doi.org/${String(paper.doi).replace(/^https?:\/\/doi\.org\//i, "")}` : (paper.url || "");
  const citationBox = `<section class="paper-citation-box"><div><span class="section-overline">SOURCE &amp; CITATION</span><h4>Paper record</h4></div><p>${escapeHTML(paperCitation(paper))}</p><div class="paper-citation-actions"><button type="button" class="secondary-button" data-copy-paper-citation>Copy citation</button><button type="button" class="secondary-button" data-copy-paper-bibtex>Copy BibTeX</button>${citationTarget ? `<a class="quiet-link" href="${escapeHTML(citationTarget)}" target="_blank" rel="noopener noreferrer">Open DOI/source ↗</a>` : ""}<a class="quiet-link" href="/api/papers/${encodeURIComponent(paper.id)}/file?inline=1" target="_blank" rel="noopener noreferrer">Open original PDF ↗</a></div><small>Finding IDs link to exact validated quotes and PDF page numbers. Verify citation metadata against the publisher.</small></section>`;
  const report = latest?.status === "completed"
    ? renderPaperAnalysis(latest)
    : `<div class="analysis-report-prompt"><span class="section-overline">YOUR PAPER REPORT</span><h3>${analysisActive ? "Your analysis is running" : latest?.status === "failed" ? "Ready to try again" : "Start the detailed analysis"}</h3><p>${analysisActive ? "The report will appear here automatically when the local model finishes." : "Research methods, data, architecture, experiments, metrics, results, and exact page citations will appear here."}</p>${!analysisActive ? `<button class="primary-button" type="button" data-analysis-analyze="${escapeHTML(paper.id)}">${latest?.status === "failed" ? "Retry analysis" : "Analyze full paper"}<span class="button-arrow">→</span></button>` : ""}</div>`;
  const headerActions = !analysisActive && latest?.status === "completed"
    ? `<div class="analysis-header-actions"><button class="secondary-button" type="button" data-jump-paper-chat>Ask this paper ↓</button><button class="secondary-button" type="button" data-analysis-analyze="${escapeHTML(paper.id)}">Analyze again</button></div>` : "";
  root.innerHTML = `<article class="analysis-detail-card"><header class="analysis-detail-header"><div><span class="section-overline">SELECTED PDF</span><h2>${escapeHTML(paper.title || paper.local_filename || "Research paper")}</h2><p>${escapeHTML((paper.authors || []).join(", ") || paper.local_filename || "Local PDF")} · ${escapeHTML(paper.year || "Year unavailable")} · ${Number(paper.page_count || 0)} pages</p></div>${headerActions}</header>${citationBox}${analysisStatus}${report}</article>`;
}
function schedulePaperSearch(query) {
  if (state.paperSearchTimer) clearTimeout(state.paperSearchTimer);
  const request = ++state.paperSearchSequence;
  $("#paper-list").setAttribute("aria-busy", "true");
  $("#library-total-label").textContent = "searching…";
  state.paperSearchTimer = setTimeout(() => {
    state.paperSearchTimer = null;
    loadPapers(query, request);
  }, 220);
}
$("#paper-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-paper-insights]");
  if (!button) return;
  if (state.paperInsightId === button.dataset.paperInsights) {
    button.setAttribute("aria-expanded", "false");
    if (state.paperInsightTimer) clearTimeout(state.paperInsightTimer);
    state.paperInsightTimer = null; state.paperInsightId = null; state.paperInsightData = null; state.paperInsightRequest += 1;
    renderPaperInsights(null);
  } else {
    $$("[data-paper-insights]", $("#paper-list")).forEach((item) => item.setAttribute("aria-expanded", String(item === button)));
    loadPaperInsights(button.dataset.paperInsights);
  }
});
$("#paper-discovery-form").addEventListener("submit", (event) => { event.preventDefault(); runPaperDiscovery(); });
$("#discovery-results").addEventListener("click", async (event) => {
  const open = event.target.closest("[data-discovery-open]");
  if (open) { await openPaperDetailsInLibrary(open.dataset.discoveryOpen); return; }
  const save = event.target.closest("[data-discovery-save]");
  if (!save || save.disabled) return;
  const paper = state.paperDiscoveryResults[Number(save.dataset.discoverySave)];
  if (!paper) return;
  save.disabled = true; save.textContent = "Saving…";
  try {
    const source = save.dataset.source;
    const sourceId = paper.source_ids?.[source] || save.dataset.sourceId;
    const result = await api("/api/papers/save-discovered", { method: "POST", body: JSON.stringify({
      project_id: state.projectId, source, source_id: sourceId, title: paper.title, doi: paper.doi, authors: paper.authors || [],
      year: paper.year, abstract: paper.abstract || "", url: paper.url || "", open_access_url: paper.open_access_url || "",
      journal: paper.journal || "", publisher: paper.publisher || "", volume: paper.volume || "", issue: paper.issue || "", pages: paper.pages || ""
    }) });
    paper.saved_paper_id = result.paper_id;
    paper.saved_local_pdf = false;
    paper.saved_report_count ||= 0;
    renderDiscoveryResults(state.paperDiscoveryResults);
    toast(result.already_in_project ? "This paper is already in the current project library." : "Paper saved to your library.");
    await loadDashboard();
  } catch (error) {
    save.disabled = false; save.textContent = "Save to library";
    toast(`Could not save paper: ${error.message}`, "error");
  }
});
$("#analysis-paper-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-select-analysis-paper]");
  if (!button || button.dataset.selectAnalysisPaper === state.analysisPaperId) return;
  state.analysisPaperId = button.dataset.selectAnalysisPaper;
  renderAnalysisPaperList();
  loadAnalysisPaper(state.analysisPaperId);
});
$("#analysis-add-pdf").addEventListener("click", () => $("#add-papers").click());
$("#analysis-open-library").addEventListener("click", () => switchView("library"));
$("#paper-insight-panel").addEventListener("click", (event) => {
  const open = event.target.closest("[data-open-paper-analysis]");
  if (open) openPaperAnalysis(open.dataset.openPaperAnalysis);
});
$("#analysis-paper-detail").addEventListener("click", (event) => {
  const evidenceRef = event.target.closest(".analysis-evidence-ref");
  if (evidenceRef) {
    event.preventDefault();
    const target = document.getElementById(evidenceRef.getAttribute("href").slice(1));
    if (target) { const details = target.closest("details"); if (details) details.open = true; target.scrollIntoView({ behavior: "smooth", block: "center" }); }
    return;
  }
  if (event.target.closest("[data-jump-paper-chat]")) {
    const chat = $("#paper-analysis-chat");
    chat?.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => $("#paper-analysis-chat input")?.focus(), 250);
    return;
  }
  const analyze = event.target.closest("[data-analysis-analyze]");
  if (analyze && !analyze.disabled) { startPaperAnalysis(analyze.dataset.analysisAnalyze, analyze); return; }
  const citation = event.target.closest("[data-copy-paper-citation]");
  const bibtex = event.target.closest("[data-copy-paper-bibtex]");
  if (citation || bibtex) {
    const paper = state.analysisPaperData?.paper || {};
    const value = citation ? paperCitation(paper) : paperBibtex(paper);
    if (!navigator.clipboard?.writeText) toast("Clipboard access is unavailable in this browser. Select and copy the citation text.", "error");
    else navigator.clipboard.writeText(value).then(() => toast(citation ? "Citation copied." : "BibTeX copied."))
      .catch(() => toast("Clipboard access is unavailable in this browser. Select and copy the citation text.", "error"));
  }
});
$("#analysis-paper-detail").addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-paper-chat-form]");
  if (!form) return;
  event.preventDefault();
  const message = String(new FormData(form).get("message") || "").trim();
  if (!message || state.paperChat.sending) return;
  const analysisId = form.dataset.analysisId;
  if (state.paperChat.analysisId !== analysisId) state.paperChat = { analysisId, messages: [], sending: false };
  state.paperChat.messages.push({ role: "user", text: message });
  state.paperChat.sending = true;
  const scrollY = window.scrollY;
  renderAnalysisPaperDetail(state.analysisPaperData);
  requestAnimationFrame(() => window.scrollTo({ top: scrollY, behavior: "instant" }));
  try {
    const answer = await api(`/api/paper-analyses/${encodeURIComponent(analysisId)}/chat`, { method: "POST", body: JSON.stringify({ message }) });
    state.paperChat.messages.push({ role: "assistant", answer: answer.answer, evidence_ids: answer.evidence_ids || [] });
  } catch (error) {
    state.paperChat.messages.push({ role: "assistant", answer: `I could not answer from the saved PDF evidence: ${error.message}`, evidence_ids: [] });
  } finally {
    state.paperChat.sending = false;
    const currentScrollY = window.scrollY;
    renderAnalysisPaperDetail(state.analysisPaperData);
    requestAnimationFrame(() => { window.scrollTo({ top: currentScrollY, behavior: "instant" }); $("#paper-analysis-chat input")?.focus(); });
  }
});
$("#paper-insight-panel").addEventListener("click", (event) => {
  const evidenceRef = event.target.closest(".analysis-evidence-ref");
  if (evidenceRef) {
    event.preventDefault();
    const target = document.getElementById(evidenceRef.getAttribute("href").slice(1));
    if (target) { const details = target.closest("details"); if (details) details.open = true; target.scrollIntoView({ behavior: "smooth", block: "center" }); }
    return;
  }
  if (event.target.closest("[data-close-paper-insights]")) {
    if (state.paperInsightTimer) clearTimeout(state.paperInsightTimer);
    state.paperInsightTimer = null; state.paperInsightId = null; state.paperInsightData = null; state.paperInsightRequest += 1;
    renderPaperInsights(null); return;
  }
  const analyze = event.target.closest("[data-analyze-paper]");
  if (analyze && !analyze.disabled) { startPaperAnalysis(analyze.dataset.analyzePaper, analyze); return; }
  const report = event.target.closest("[data-open-insight-report]");
  if (report) openInsightReportChat(report.dataset.openInsightReport);
  const citation = event.target.closest("[data-copy-paper-citation]");
  const bibtex = event.target.closest("[data-copy-paper-bibtex]");
  if (citation || bibtex) {
    const paper = state.paperInsightData?.paper || {};
    const text = citation ? paperCitation(paper) : paperBibtex(paper);
    if (!navigator.clipboard?.writeText) toast("Clipboard access is unavailable in this browser. Select and copy the citation text.", "error");
    else navigator.clipboard.writeText(text).then(() => toast(citation ? "Citation copied." : "BibTeX copied."))
      .catch(() => toast("Clipboard access is unavailable in this browser. Select and copy the citation text.", "error"));
  }
});
$("#paper-insight-panel").addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-paper-chat-form]");
  if (!form) return;
  event.preventDefault();
  const message = String(new FormData(form).get("message") || "").trim();
  if (!message || state.paperChat.sending) return;
  const analysisId = form.dataset.analysisId;
  if (state.paperChat.analysisId !== analysisId) state.paperChat = { analysisId, messages: [], sending: false };
  state.paperChat.messages.push({ role: "user", text: message });
  state.paperChat.sending = true;
  const scrollY = window.scrollY;
  renderPaperInsights(state.paperInsightData);
  requestAnimationFrame(() => window.scrollTo({ top: scrollY, behavior: "instant" }));
  try {
    const answer = await api(`/api/paper-analyses/${encodeURIComponent(analysisId)}/chat`, { method: "POST", body: JSON.stringify({ message }) });
    state.paperChat.messages.push({ role: "assistant", answer: answer.answer, evidence_ids: answer.evidence_ids || [] });
  } catch (error) {
    state.paperChat.messages.push({ role: "assistant", answer: `I could not answer from the saved PDF evidence: ${error.message}`, evidence_ids: [] });
  } finally {
    state.paperChat.sending = false;
    const currentScrollY = window.scrollY;
    renderPaperInsights(state.paperInsightData);
    requestAnimationFrame(() => { window.scrollTo({ top: currentScrollY, behavior: "instant" }); $("#paper-analysis-chat input")?.focus(); });
  }
});
async function loadRuns() {
  try {
    const runs = await api("/api/runs?limit=50");
    const html = runs.length ? runs.map((run) => `<article class="run-card" data-run="${escapeHTML(run.id)}" tabindex="0" role="button"><div class="run-card-top"><span class="run-icon">${run.status === "running" ? "◌" : "✳"}</span><span class="status-chip ${escapeHTML(run.status)}">${escapeHTML(statusLabel(run.status))}</span></div><h3>${escapeHTML(run.question)}</h3><div class="run-card-meta"><span>${escapeHTML(run.project_name || "Research project")}</span><span>${escapeHTML(dateLabel(run.created_at))}</span></div><div class="run-card-bottom"><span>${Number(run.paper_count || 0)} papers found</span><span>Open report →</span></div></article>`).join("") : `<div class="empty-state"><div class="empty-icon">✳</div><strong>No research runs yet</strong><span>Start your first investigation from Overview.</span></div>`;
    if ($("#all-runs").innerHTML !== html) { $("#all-runs").innerHTML = html; bindRunRows($("#all-runs")); }
  } catch (error) { toast(`Could not load runs: ${error.message}`, "error"); }
}
function renderAgentTrace() {
  const trace = state.agentTrace;
  const run = trace.run;
  const badge = $("#agent-live-badge");
  const content = $("#agent-trace-content");
  const progress = $("#agent-trace-progress");
  const counter = $("#agent-trace-counter");
  const previous = $("#agent-trace-prev");
  const next = $("#agent-trace-next");
  const pause = $("#agent-trace-pause");
  if (!run) {
    badge.className = "agent-live-badge ready";
    badge.innerHTML = `<span class="live-pulse"></span> READY`;
    content.innerHTML = `<div class="agent-trace-idle"><span class="trace-sparkle">✦</span><div><strong>Ready when you are</strong><p>Start a research run and watch the team unpack it together.</p></div></div>`;
    progress.innerHTML = ""; counter.textContent = "LIVE JOURNAL";
    pause.hidden = true; previous.disabled = true; next.disabled = true;
    return;
  }
  const active = run.status === "running" || run.status === "queued";
  badge.className = `agent-live-badge ${active ? "live" : "done"}`;
  badge.innerHTML = `<span class="live-pulse"></span> ${active ? (run.status === "queued" ? "UP NEXT" : "LIVE · IN PROGRESS") : "LATEST TRACE"}`;
  const events = trace.events;
  const event = events[trace.index] || { agent: "Agent team", stage: run.stage || "waiting", message: active ? "The run is underway. The next saved agent update will appear here." : "This run has no saved agent updates yet." };
  const initials = String(event.agent || "Agent").split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
  const stage = String(event.stage || "working").replaceAll("_", " ");
  const current = trace.index === events.length - 1;
  const stepLabel = active && current ? "CURRENT UPDATE" : `TRACE STEP ${String(trace.index + 1).padStart(2, "0")}`;
  content.innerHTML = `<article class="agent-trace-slide"><div class="trace-agent-avatar">${escapeHTML(initials || "✦")}</div><div class="trace-agent-copy"><div class="trace-agent-meta"><span>${escapeHTML(stepLabel)}</span><span>${escapeHTML(dateLabel(event.created_at))}</span><span>${escapeHTML(stage)}</span></div><h3>${escapeHTML(event.agent || "Agent team")}</h3><p>${escapeHTML(event.message || "Working through the next step…")}</p></div><button class="trace-open-run" type="button" data-open-trace-run="${escapeHTML(run.id)}">Open full journal ↗</button></article>`;
  progress.innerHTML = events.map((_, index) => `<button class="trace-dot ${index === trace.index ? "active" : ""} ${index === events.length - 1 ? "latest" : ""}" type="button" data-trace-step="${index}" aria-label="Show trace step ${index + 1}" title="Trace step ${index + 1}"></button>`).join("");
  counter.textContent = `${run.status === "running" ? "LIVE TRACE" : run.status === "queued" ? "QUEUED TRACE" : "RECENT TRACE"} · ${String(trace.index + 1).padStart(2, "0")} / ${String(events.length).padStart(2, "0")}`;
  pause.hidden = !active || events.length < 2;
  pause.textContent = trace.paused ? "▶" : "Ⅱ";
  pause.setAttribute("aria-label", trace.paused ? "Resume carousel" : "Pause carousel");
  pause.title = trace.paused ? "Resume carousel" : "Pause carousel";
  previous.disabled = events.length < 2;
  next.disabled = events.length < 2;
}
async function loadAgentTrace() {
  if (state.view !== "agents") return;
  try {
    const runs = await api("/api/runs?limit=10");
    const runSummary = runs.find((item) => item.status === "running") || runs.find((item) => item.status === "queued") || runs[0];
    if (!runSummary) {
      state.agentTrace = { ...state.agentTrace, runId: null, run: null, events: [], index: 0, revision: "", active: false };
      renderAgentTrace();
      return;
    }
    const run = await api(`/api/runs/${encodeURIComponent(runSummary.id)}`);
    if (state.view !== "agents") return;
    const events = (run.events || []).slice(-5);
    if (!events.length) {
      const quietMessage = run.status === "queued" ? "Your run is queued and will leave a live trace when work begins."
        : run.status === "running" ? "The run is in progress; the first journal update will appear here."
          : "The run finished without a saved agent update.";
      events.push({ agent: "Agent team", stage: run.stage || "waiting", message: quietMessage });
    }
    const revision = JSON.stringify([run.id, run.status, run.progress, run.stage, events]);
    const changed = revision !== state.agentTrace.revision;
    const newRun = run.id !== state.agentTrace.runId;
    const latestChanged = events.length > state.agentTrace.events.length
      || JSON.stringify(events.at(-1)) !== JSON.stringify(state.agentTrace.events.at(-1));
    state.agentTrace.runId = run.id;
    state.agentTrace.run = run;
    state.agentTrace.active = run.status === "running" || run.status === "queued";
    if (changed) {
      state.agentTrace.events = events;
      if (newRun || latestChanged) state.agentTrace.index = events.length - 1;
      else state.agentTrace.index = Math.min(state.agentTrace.index, events.length - 1);
      state.agentTrace.revision = revision;
      renderAgentTrace();
    }
  } catch (error) {
    $("#agent-live-badge").className = "agent-live-badge done";
    $("#agent-live-badge").innerHTML = `<span class="live-pulse"></span> JOURNAL OFFLINE`;
    $("#agent-trace-content").innerHTML = `<div class="agent-trace-idle"><span class="trace-sparkle">◌</span><div><strong>Couldn't load the live trace</strong><p>${escapeHTML(error.message)}</p></div></div>`;
  }
}
function moveAgentTrace(amount) {
  const events = state.agentTrace.events;
  if (events.length < 2) return;
  state.agentTrace.index = (state.agentTrace.index + amount + events.length) % events.length;
  renderAgentTrace();
}
function listBlock(title, items) {
  if (!Array.isArray(items) || !items.length) return "";
  return `<section class="detail-panel"><h2>${escapeHTML(title)}</h2><ul class="detail-list">${items.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul></section>`;
}
function clarifyingQuestionsBlock(questions, run) {
  if (!Array.isArray(questions) || !questions.length) return "";
  if (state.scopeRefinement.runId !== run.id) state.scopeRefinement = { runId: run.id, answers: [] };
  const canDiscuss = ["completed", "partial"].includes(run.status);
  const fields = questions.slice(0, 5).map((question, index) => {
    const prompt = String(question || "").trim();
    if (!prompt) return "";
    const fieldId = `scope-answer-${run.id}-${index}`;
    const answer = state.scopeRefinement.answers[index] || "";
    return `<article class="scope-question-item"><label for="${fieldId}"><span class="scope-question-number">Q${String(index + 1).padStart(2, "0")}</span>${escapeHTML(prompt)}</label><textarea id="${fieldId}" data-scope-answer="${index}" maxlength="800" rows="2" placeholder="Your answer, preference, or constraint…">${escapeHTML(answer)}</textarea>${canDiscuss ? `<button type="button" class="scope-discuss-link" data-discuss-clarifier="${index}">Help me decide in report chat ↗</button>` : ""}</article>`;
  }).join("");
  if (!fields) return "";
  return `<section class="detail-panel scope-clarification-panel"><div><span class="section-overline">MAKE THE NEXT SEARCH FIT YOUR PROJECT</span><h2>Questions to refine the scope</h2><p>Answer the questions that matter. Leave the rest open; the report keeps its assumptions visible.</p></div><form data-refine-run="${escapeHTML(run.id)}" class="scope-refinement-form"><div class="scope-question-list">${fields}</div><div class="scope-refinement-footer"><span>A new run will search the trusted scholarly indexes using your answers.</span><button class="primary-button" type="submit">Start refined search <span class="button-arrow">→</span></button></div></form></section>`;
}
function literatureReviewBlock(appraisals, coverage, search, pdfs, generatedAt, citationTargets, run) {
  const items = Array.isArray(appraisals) ? appraisals : [];
  const branches = Array.isArray(search?.branches) ? search.branches : [];
  const groups = new Map();
  for (const item of items) groups.set(item.paper_id, [...(groups.get(item.paper_id) || []), item]);
  const labels = { what_studied: "What the paper studied", relevance: "Relevance to your question", strengths: "Evidence-backed strengths", limitations: "Stated limitations" };
  const cards = [...groups.values()].map((facets) => {
    const paper = facets[0];
    const target = citationTargets?.get(paper.source_label);
    const title = target
      ? `<a href="${escapeHTML(target)}" target="_blank" rel="noopener noreferrer">[${escapeHTML(paper.source_label || "SOURCE")}] ${escapeHTML(paper.title || "Source record")} ↗</a>`
      : `<strong>[${escapeHTML(paper.source_label || "SOURCE")}] ${escapeHTML(paper.title || "Source record")}</strong>`;
    const meta = [paper.year, paper.source, paper.location].filter(Boolean).map(escapeHTML).join(" · ");
    const facetCards = facets.map((facet) => `<article class="literature-facet ${facet.status === "not_assessable" ? "not-assessable" : ""}"><h4>${escapeHTML(labels[facet.aspect] || analysisLabel(facet.aspect))}</h4><p>${escapeHTML(facet.assessment || "Not assessable from the text supplied to this run.")}</p>${facet.evidence_quote ? `<blockquote>“${escapeHTML(facet.evidence_quote)}”</blockquote><span class="literature-evidence-location">${escapeHTML(facet.location || "Exact source excerpt")} · ${escapeHTML(facet.source_label || "Source")}</span>` : `<span class="literature-evidence-location">Not assessable from the available excerpt</span>`}</article>`).join("");
    return `<article class="annotated-paper-card"><header class="annotated-paper-heading">${title}<span>${meta}</span></header><div class="literature-facets">${facetCards}</div></article>`;
  }).join("");
  const stats = [
    ["Scholarly index hits", search?.candidate_hits ?? "—"],
    ["Unique candidates", search?.unique_candidates ?? search?.unique_papers ?? "—"],
    ["Source links retained", search?.retained_source_links ?? "—"],
    ["Records analyzed", search?.analysis_records ?? "—"],
    ["Papers with quoted appraisals", coverage?.papers_with_assessments ?? 0],
    ["Index hits screened out", search?.screened_out_hits ?? "—"],
  ].map(([label, value]) => `<div><strong>${escapeHTML(String(value))}</strong><span>${escapeHTML(label)}</span></div>`).join("");
  const branchList = branches.map((branch) => `<article class="literature-branch"><strong>${escapeHTML(branch.name || "Search branch")}</strong><code>${escapeHTML(branch.query || "")}</code><span>${escapeHTML(branch.purpose || "")}</span></article>`).join("");
  const indexList = Array.isArray(search?.sources) ? search.sources.join(" · ") : "Crossref · Europe PMC · OpenAlex";
  const note = coverage?.note || "Appraisals are limited to exact excerpts available to this run. A missing facet is not evidence that a study is weak or has no limitations.";
  const completed = ["completed", "partial"].includes(run?.status);
  const noVerifiedAppraisals = items.length > 0 && Number(coverage?.evidence_backed_facets || 0) === 0;
  const emptyMessage = items.length
    ? "Appraisals will appear when this research run completes."
    : "This saved run predates annotated paper reviews. A new run can reuse its question and brief, refresh the trusted-index search, and include the project's attached PDFs.";
  const empty = items.length ? cards : `<div class="metric-empty">${escapeHTML(emptyMessage)}</div>`;
  const rerunAction = completed && (!items.length || noVerifiedAppraisals)
    ? `<div class="metric-empty">${items.length ? "No appraisal quote could be verified from the available excerpts. Connect a local model or attach full-text PDFs, then try again." : "Create the new annotated review from this run's saved scope."}${items.length ? `<button class="secondary-button literature-rerun-button" type="button" data-review-model-settings>Open model settings</button>` : ""}<button class="secondary-button literature-rerun-button" type="button" data-review-rerun>Run this review again <span class="button-arrow">→</span></button></div>` : "";
  const includedPdfs = Number(pdfs?.included_in_run || 0);
  const excludedPdfs = Number(pdfs?.excluded_for_topic || 0);
  const suppliedSources = `${Number(search?.web_pages_read || 0)} selected scholarly web page(s) · ${includedPdfs} topic-matched project PDF(s)${excludedPdfs ? ` · ${excludedPdfs} unrelated project PDF(s) left in library` : ""}`;
  const screeningNote = search?.screening_method
    ? `${Number(search?.screened_out_hits || 0)} index hits were excluded for insufficient overlap between the research topic and their title/abstract.`
    : "This older run predates automatic relevance screening; inspect source titles before relying on them.";
  return `<section class="detail-panel literature-review-panel"><div class="literature-review-heading"><div><span class="section-overline">EVIDENCE REVIEW</span><h2>Literature review</h2><p>Search scope, paper-by-paper annotations, and their evidence in one place.</p></div><span class="metric-coverage-chip">Generated ${escapeHTML(dateLabel(generatedAt))}</span></div><div class="literature-coverage"><div class="literature-coverage-stats">${stats}</div><div class="literature-source-line"><strong>Trusted indexes</strong><span>${escapeHTML(indexList)}</span></div><div class="literature-source-line"><strong>Additional supplied sources</strong><span>${escapeHTML(suppliedSources)}</span></div><div class="literature-source-line"><strong>Topic screening</strong><span>${escapeHTML(screeningNote)}</span></div>${branchList ? `<div class="literature-branches"><strong>Search branches and queries</strong>${branchList}</div>` : ""}</div><div class="annotated-bibliography-heading"><div><span class="section-overline">ANNOTATED BIBLIOGRAPHY</span><h3>What each paper contributes</h3></div><span>${Number(coverage?.evidence_backed_facets || 0)} evidence-backed facets</span></div><p class="metric-coverage-note">Each assessment is tied to an exact excerpt. Relevance is an interpretation; strengths and limitations are included only when supported by the supplied text. An abstract may not expose enough detail to judge a full study.</p><div class="annotated-paper-list">${empty}${rerunAction}</div><p class="metric-coverage-note">${escapeHTML(note)}</p></section>`;
}
function studyDetailsBlock(details, coverage, citationTargets) {
  const items = Array.isArray(details) ? details : [];
  const note = coverage?.note || "Only exact quotes from text available to this run are shown. Full papers may report more methodology and experiment details.";
  if (!items.length) {
    const emptyMessage = coverage
      ? "No explicit method or experiment details were found in the text available to this run. Abstracts often omit setup, baselines, and evaluation protocol; attach full-text PDFs for a deeper capture."
      : "This report predates source-quoted method capture. New runs show exact methodology and experiment excerpts from their available paper text; attach full-text PDFs for deeper coverage.";
    return `<section class="detail-panel source-methods-panel"><div><span class="section-overline">WHAT PRIOR PAPERS DID</span><h2>Methods and experiments in prior work</h2></div><div class="metric-empty">${escapeHTML(emptyMessage)}</div><p class="metric-coverage-note">${escapeHTML(note)}</p></section>`;
  }
  const grouped = new Map();
  for (const item of items) grouped.set(item.paper_id, [...(grouped.get(item.paper_id) || []), item]);
  const groups = [...grouped.values()].map((facts) => {
    const paper = facts[0];
    const target = citationTargets?.get(paper.source_label);
    const title = target ? `<a href="${escapeHTML(target)}" target="_blank" rel="noopener noreferrer">[${escapeHTML(paper.source_label)}] ${escapeHTML(paper.title || "Source record")} ↗</a>` : `<strong>[${escapeHTML(paper.source_label || "SOURCE")}] ${escapeHTML(paper.title || "Source record")}</strong>`;
    const meta = [paper.year, paper.source, paper.location].filter(Boolean).map(escapeHTML).join(" · ");
    return `<article class="study-detail-group"><div class="study-detail-heading">${title}<span>${meta}</span></div><div class="study-detail-facts">${facts.map((fact) => `<div class="study-detail-fact"><span>${escapeHTML(analysisLabel(fact.aspect))}</span><blockquote>“${escapeHTML(fact.evidence_quote || "")}"</blockquote></div>`).join("")}</div></article>`;
  }).join("");
  const count = Number(coverage?.detail_count ?? items.length);
  const represented = Number(coverage?.records_with_details ?? grouped.size);
  return `<section class="detail-panel source-methods-panel"><div class="metric-evidence-heading"><div><span class="section-overline">WHAT PRIOR PAPERS DID</span><h2>Methods and experiments in prior work</h2></div><span class="metric-coverage-chip">${count} exact excerpts · ${represented} papers</span></div><div class="study-detail-groups">${groups}</div><p class="metric-coverage-note">${escapeHTML(note)}</p></section>`;
}
function analysisLabel(value) { return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function analysisValue(value, citationTargets) {
  if (Array.isArray(value)) {
    if (!value.length) return "<span class=\"analysis-empty\">None recorded</span>";
    if (value.every((item) => item && typeof item === "object" && !Array.isArray(item))) {
      return `<div class="analysis-cards">${value.map((item) => {
        const entries = Object.entries(item);
        const headingKey = ["phase", "question", "metric", "name", "paper", "title", "value"].find((key) => item[key]);
        const heading = headingKey ? item[headingKey] : "Research detail";
        return `<article class="analysis-card"><h3>${analysisValue(heading, citationTargets)}</h3>${entries.filter(([key]) => key !== headingKey).map(([key, child]) => `<div class="analysis-row"><strong>${escapeHTML(analysisLabel(key))}</strong><div>${analysisValue(child, citationTargets)}</div></div>`).join("")}</article>`;
      }).join("")}</div>`;
    }
    return `<ul class="detail-list">${value.map((item) => `<li>${analysisValue(item, citationTargets)}</li>`).join("")}</ul>`;
  }
  if (value && typeof value === "object") return `<div class="analysis-object">${Object.entries(value).map(([key, item]) => `<div class="analysis-row"><strong>${escapeHTML(analysisLabel(key))}</strong><div>${analysisValue(item, citationTargets)}</div></div>`).join("")}</div>`;
  return escapeHTML(value ?? "").replace(/\[(P\d+)\]/g, (label, id) => {
    const target = citationTargets?.get(id);
    return target ? `<a class="inline-cite" href="${escapeHTML(target)}" target="_blank" rel="noopener noreferrer">${label}</a>` : label;
  });
}
function analysisBlock(title, analysis, citationTargets) {
  if (!analysis || typeof analysis !== "object") return "";
  const body = analysisValue(analysis, citationTargets);
  return body ? `<section class="detail-panel analysis-panel"><h2>${escapeHTML(title)}</h2>${body}</section>` : "";
}
function metricsBlock(result, citationTargets) {
  const metrics = Array.isArray(result.study_metrics) ? result.study_metrics : [];
  const coverage = result.metrics_coverage || {};
  const cards = metrics.map((metric) => {
    const target = citationTargets?.get(metric.source_label) || metric.url || "";
    const source = target ? `<a class="metric-source-link" href="${escapeHTML(target)}" target="_blank" rel="noopener noreferrer">${escapeHTML(metric.source_label || "Source")} · ${escapeHTML(metric.title || "Open source")} ↗</a>` : `<span class="metric-source-link">${escapeHTML(metric.title || "Source link unavailable")}</span>`;
    return `<article class="reported-metric-card"><div class="reported-metric-top"><h3>${escapeHTML(metric.metric || "Unlabelled metric")}</h3>${source}</div>${metric.what_it_measures ? `<p>${escapeHTML(metric.what_it_measures)}</p>` : ""}${metric.reported_result ? `<div class="metric-result"><strong>Reported result</strong><span>${escapeHTML(metric.reported_result)}</span></div>` : ""}${metric.evidence_quote ? `<blockquote>“${escapeHTML(metric.evidence_quote)}”</blockquote>` : ""}</article>`;
  }).join("");
  const note = coverage.note || "Only measures named in the available source text are listed. Full-text methods and tables may contain additional metrics.";
  const coverageLine = `${Number(coverage.metric_count ?? metrics.length)} source-reported metric${Number(coverage.metric_count ?? metrics.length) === 1 ? "" : "s"} · ${Number(coverage.analysis_records || 0)} records sent for analysis`;
  const planned = result.research_strategy?.experimental_plan?.flatMap?.((phase) => Array.isArray(phase.metrics) ? phase.metrics : []) || [];
  return `<section class="detail-panel metric-evidence-panel"><div class="metric-evidence-heading"><div><span class="section-overline">MEASURES FOUND IN THE SOURCES</span><h2>Reported study metrics</h2></div><span class="metric-coverage-chip">${escapeHTML(coverageLine)}</span></div>${cards ? `<div class="reported-metric-grid">${cards}</div>` : `<div class="metric-empty">No metric names were explicit in the text available for this run. Open full texts or PDFs to check their methods and results tables.</div>`}<p class="metric-coverage-note">${escapeHTML(note)}</p>${planned.length ? `<div class="candidate-metric-block"><h3>Candidate metrics for your plan</h3><p>These are proposed evaluation measures, not metrics already reported by the retrieved papers.</p>${analysisValue(planned, citationTargets)}</div>` : ""}</section>`;
}
function formatChatContent(value, citationTargets) {
  const safe = escapeHTML(value).replace(/\[(P\d+)\]/g, (label, citation) => {
    const target = citationTargets.get(citation);
    if (!target || !(target.startsWith("/") || /^https?:\/\//i.test(target))) return label;
    return `<a class="chat-citation" href="${escapeHTML(target)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });
  return safe.split(/\n{2,}/).map((paragraph) => `<p>${paragraph.replaceAll("\n", "<br>")}</p>`).join("");
}
function renderReportChat() {
  const root = $("#run-chat-root");
  if (!root || !state.reportChat.runId) return;
  const chat = state.reportChat;
  const messages = chat.messages.map((message) => `<article class="report-chat-message ${message.role === "user" ? "from-user" : "from-assistant"}"><span class="report-chat-avatar">${message.role === "user" ? "You" : "R"}</span><div class="report-chat-message-body"><strong>${message.role === "user" ? "You" : "Research assistant"}</strong><div class="report-chat-copy">${formatChatContent(message.content || "", chat.citationTargets)}</div></div></article>`).join("");
  const suggestions = !chat.messages.length && chat.ready && state.modelConnected
    ? `<div class="report-chat-suggestions"><button type="button" data-chat-suggestion="What are the strongest findings, and which sources support them?">Strongest findings</button><button type="button" data-chat-suggestion="What does this report establish about the current state of the art, and what remains unknown?">Ask about SOTA</button><button type="button" data-chat-suggestion="What should I do next to strengthen or validate this work?">Next steps</button></div>` : "";
  const connect = chat.ready && !state.modelConnected
    ? `<div class="report-chat-connect"><span>Connect a local model to ask questions about this report.</span><button type="button" class="secondary-button" data-chat-connect>Open model settings</button></div>` : "";
  const form = chat.ready && state.modelConnected
    ? `<form id="report-chat-form" class="report-chat-form"><textarea name="message" maxlength="4000" rows="2" placeholder="Ask about a finding, source, metric, or next step…" ${chat.sending ? "disabled" : ""}>${escapeHTML(chat.draft)}</textarea><button class="primary-button" type="submit" ${chat.sending ? "disabled" : ""}>${chat.sending ? "Thinking…" : "Ask"}<span class="button-arrow">${chat.sending ? "◌" : "↑"}</span></button></form>` : "";
  const error = chat.error ? `<div class="report-chat-error" role="alert">${escapeHTML(chat.error)} <button type="button" data-chat-retry>Try again</button><button type="button" data-chat-connect>Model settings</button></div>` : "";
  const waiting = chat.loading ? `<div class="report-chat-waiting">Loading this report's conversation…</div>` : "";
  const pending = chat.sending ? `<article class="report-chat-message from-assistant"><span class="report-chat-avatar">R</span><div class="report-chat-message-body"><strong>Research assistant</strong><div class="chat-thinking"><span></span><span></span><span></span> Reading the report and its saved evidence</div></div></article>` : "";
  const unavailable = !chat.ready ? `<div class="report-chat-connect"><span>Report chat will be ready when the research run finishes.</span></div>` : "";
  root.innerHTML = `<section class="detail-panel report-chat-panel" aria-labelledby="report-chat-title"><div class="report-chat-heading"><div><span class="section-overline">ASK A FOLLOW-UP</span><h2 id="report-chat-title">Talk with this report</h2><p>Answers use the report and its saved source evidence. Citations open the source.</p></div><span class="report-chat-local"><span></span>Local model</span></div><div class="report-chat-messages">${messages}${pending}${!chat.messages.length && !chat.loading ? `<div class="report-chat-empty">Ask for a plain-language explanation, compare findings, or question a recommendation.</div>` : ""}${waiting}</div>${suggestions}${connect}${unavailable}${error}${form}</section>`;
  if (chat.sending) root.querySelector(".report-chat-messages")?.scrollTo({ top: root.querySelector(".report-chat-messages").scrollHeight });
}
async function loadReportChat(id, ready, citationTargets) {
  const changed = state.reportChat.runId !== id;
  if (changed) state.reportChat = { runId: id, ready: false, loaded: false, loading: false, messages: [], sending: false, draft: "", error: "", citationTargets: new Map() };
  const readinessChanged = state.reportChat.ready !== ready;
  state.reportChat.ready = ready;
  state.reportChat.citationTargets = citationTargets;
  if (!ready) {
    if (changed || readinessChanged) renderReportChat();
    return;
  }
  if (state.reportChat.loaded || state.reportChat.loading) {
    if (changed || readinessChanged) renderReportChat();
    return;
  }
  state.reportChat.loading = true;
  renderReportChat();
  try {
    const data = await api(`/api/runs/${encodeURIComponent(id)}/chat`);
    if (state.reportChat.runId !== id) return;
    state.reportChat.messages = data.messages || [];
    state.reportChat.loaded = true;
    state.reportChat.error = "";
  } catch (error) {
    if (state.reportChat.runId !== id) return;
    state.reportChat.loaded = true;
    state.reportChat.error = error.message;
  } finally {
    if (state.reportChat.runId === id) {
      state.reportChat.loading = false;
      renderReportChat();
    }
  }
}
async function sendReportChat(value) {
  const chat = state.reportChat;
  const message = String(value || "").trim();
  if (!message || chat.sending || !chat.ready || !state.modelConnected) return;
  chat.sending = true; chat.error = ""; chat.draft = "";
  renderReportChat();
  try {
    const response = await api(`/api/runs/${encodeURIComponent(chat.runId)}/chat`, { method: "POST", body: JSON.stringify({ message }) });
    if (state.reportChat.runId === chat.runId) chat.messages = response.messages || [...chat.messages, { role: "user", content: message }, response.message];
  } catch (error) {
    if (state.reportChat.runId === chat.runId) { chat.error = error.message; chat.draft = message; }
  } finally {
    if (state.reportChat.runId === chat.runId) {
      chat.sending = false; renderReportChat();
      const messages = $("#run-chat-root .report-chat-messages");
      if (messages) messages.scrollTo({ top: messages.scrollHeight, behavior: "smooth" });
    }
  }
}
async function loadRunDetail(id, { background = false } = {}) {
  const alreadyVisible = state.view === "detail" && state.detailRunId === id;
  state.detailRunId = id;
  if (!background) switchView("detail");
  if (!background || !alreadyVisible) $("#run-detail-content").innerHTML = `<div class="empty-state"><div class="empty-icon">◌</div><strong>Opening research journal</strong><span>Loading sources and agent notes…</span></div>`;
  try {
    const run = await api(`/api/runs/${encodeURIComponent(id)}`);
    if (state.detailRunId !== id) return;
    state.detailRun = run;
    const result = run.result || {};
    const researchMap = result.research_map && typeof result.research_map === "object" ? { ...result.research_map } : {};
    delete researchMap.clarifying_questions;
    const running = run.status === "running" || run.status === "queued";
    const papers = run.papers || [];
    const refs = new Map((Array.isArray(result.citation_refs) ? result.citation_refs : []).map((ref) => [ref.paper_id, ref.label]));
    const citationTargets = new Map();
    for (const paper of papers) {
      const label = refs.get(paper.id);
      if (!label) continue;
      citationTargets.set(label, paper.local_filename ? `/api/papers/${encodeURIComponent(paper.id)}/file` : (paper.url || (paper.doi ? `https://doi.org/${paper.doi}` : "#")));
    }
    const reportReady = run.status === "completed" || run.status === "partial";
    await loadReportChat(id, reportReady, citationTargets);
    if (state.detailRunId !== id) return;
    const revision = JSON.stringify([run.id, run.status, run.progress, run.stage, run.updated_at, run.result, run.papers, run.claims, run.events]);
    if (background && alreadyVisible && state.lastDetailRevision === revision) return;
    if (background && alreadyVisible && document.activeElement?.matches("[data-scope-answer]")) return;
    const scrollY = window.scrollY;
    $("#detail-status").textContent = statusLabel(run.status);
    $("#detail-status").className = `run-status-pill ${escapeHTML(run.status)}`;
    const claims = run.claims || [];
    const events = run.events || [];
    const paperList = papers.length ? papers.slice(0, 20).map((paper) => {
      const target = paper.local_filename ? `/api/papers/${encodeURIComponent(paper.id)}/file` : (paper.url || (paper.doi ? `https://doi.org/${paper.doi}` : "#"));
      return `<div class="detail-paper"><a href="${escapeHTML(target)}" target="_blank" rel="noopener noreferrer"><span class="citation-label">${escapeHTML(refs.get(paper.id) || "SOURCE")}</span>${escapeHTML(paper.title)}</a><span>${escapeHTML(paper.year || "Year unknown")} · ${escapeHTML(paper.source)}${paper.local_filename ? ` · ${escapeHTML(paper.local_filename)}` : ""}${paper.doi ? ` · DOI ${escapeHTML(paper.doi)}` : ""}</span></div>`;
    }).join("") : `<div class="event-copy">Search results will appear here.</div>`;
    const claimsHTML = claims.length ? `<section class="detail-panel"><h2>Evidence claims <span class="section-overline">SOURCE PASSAGES</span></h2>${claims.map((claim) => `<div class="claim-card"><p>${escapeHTML(claim.text)}</p><blockquote>${escapeHTML(claim.evidence)}</blockquote>${claim.paper_title ? `<div class="event-copy">Source: ${claim.paper_url ? `<a href="${escapeHTML(claim.paper_url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(claim.paper_title)}</a>` : escapeHTML(claim.paper_title)} · ${escapeHTML(claim.paper_source || "record")}${claim.location ? ` · ${escapeHTML(claim.location)}` : ""}</div>` : ""}<span class="claim-verdict ${claim.status === "reject" ? "reject" : ""}">${escapeHTML(claim.status)}</span></div>`).join("")}</section>` : "";
    const eventsHTML = events.map((event) => `<div class="event-row"><span class="event-dot"></span><div class="event-copy"><strong>${escapeHTML(event.agent)} · ${escapeHTML(event.stage)}</strong>${escapeHTML(event.message)}</div></div>`).join("");
    const sourceErrors = result.search?.source_errors || [];
    $("#run-detail-content").innerHTML = `<div class="detail-header"><div class="detail-header-top"><div class="eyebrow"><span class="eyebrow-line"></span> ${running ? "TEAM IN PROGRESS" : "RESEARCH JOURNAL"}</div><div class="detail-header-actions">${reportReady ? `<button class="secondary-button" type="button" data-jump-report-chat>Ask this report ↓</button>` : ""}<a class="secondary-button report-download" href="/api/runs/${encodeURIComponent(run.id)}/report.md">Download report ↓</a></div></div><h1>${escapeHTML(run.question)}</h1><div class="detail-meta"><span>${escapeHTML(dateLabel(run.created_at))}</span><span>${papers.length} papers saved</span><span>${result.model_available ? "Local model analysis" : "Search and metadata"}</span></div><div class="progress-track"><span style="width:${Math.max(3, Number(run.progress || 0))}%"></span></div>${running ? `<div class="run-meta" style="margin-top:8px">Current stage: ${escapeHTML(run.stage)} · ${run.progress}%</div>` : ""}${run.error ? `<div class="run-meta" style="margin-top:8px;color:#a45d4c">${escapeHTML(run.error)}</div>` : ""}</div>
      <div class="detail-grid"><div style="display:grid;gap:12px"><section class="detail-panel"><h2>Research synthesis</h2><div class="detail-summary">${escapeHTML(result.executive_summary || (running ? "Your research team is searching public scholarly indexes. This report will update as each stage completes." : "The run finished without a synthesis."))}</div></section>${analysisBlock("Research brief", run.brief, citationTargets)}${analysisBlock("Research map", researchMap, citationTargets)}${clarifyingQuestionsBlock(result.clarifying_questions, run)}${literatureReviewBlock(result.paper_appraisals, result.paper_appraisal_coverage, result.search, result.pdfs, result.generated_at || run.updated_at, citationTargets, run)}
      ${listBlock("Themes and synthesis", result.themes)}${listBlock("Contradictions to explore", result.contradictions)}${listBlock("Potential gaps · unconfirmed", result.research_gaps)}${studyDetailsBlock(result.study_details, result.study_details_coverage, citationTargets)}${metricsBlock(result, citationTargets)}${analysisBlock("Novelty assessment · provisional", result.novelty_analysis, citationTargets)}${analysisBlock("Impact and feasibility", result.impact_feasibility, citationTargets)}${analysisBlock("Research direction and publication readiness", result.research_strategy, citationTargets)}${listBlock("Suggested next steps", result.next_steps)}${claimsHTML}${listBlock("Limitations and open questions", result.limitations)}${listBlock("Reviewer notes", result.reviewer_notes)}${result.reviewer_issues?.length ? `<section class="detail-panel"><h2>Adversarial review</h2>${result.reviewer_issues.map((issue) => `<div class="claim-card"><span class="claim-verdict ${issue.severity === "critical" ? "reject" : ""}">${escapeHTML(issue.severity || "review")}</span><p style="margin-top:8px">${escapeHTML(issue.issue || "")}</p><div class="event-copy">Suggested action: ${escapeHTML(issue.action || "Review this conclusion against the source text.")}</div></div>`).join("")}</section>` : ""}</div>
      <div style="display:grid;align-content:start;gap:12px"><section class="detail-panel"><h2>Sources <span class="section-overline">${papers.length} RECORDS</span></h2>${paperList}${papers.length > 20 ? `<div class="event-copy">Showing first 20 source links. Open Paper library for the full retained set.</div>` : ""}</section><section class="detail-panel"><h2>Agent journal</h2>${eventsHTML || `<div class="event-copy">Agent updates will appear here.</div>`}</section>${sourceErrors.length ? `<section class="detail-panel"><h2>Source availability</h2><ul class="detail-list">${sourceErrors.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul></section>` : ""}</div></div>`;
    state.lastDetailRevision = revision;
    if (running) state.activeRunId = id;
    else if (state.activeRunId === id) state.activeRunId = null;
    if (background && alreadyVisible) requestAnimationFrame(() => window.scrollTo({ top: scrollY, behavior: "instant" }));
    return true;
  } catch (error) {
    if (!background) $("#run-detail-content").innerHTML = `<div class="empty-state"><strong>Could not load this research run</strong><span>${escapeHTML(error.message)}</span></div>`;
    return false;
  }
}
function collectBrief(formData) {
  const fields = { brief_goal: "goal", brief_domain: "domain", brief_data: "data", brief_methods: "methods",
    brief_contribution: "contribution", brief_resources: "resources", brief_timeline: "timeline", brief_success: "success_criteria" };
  const brief = {};
  for (const [formKey, briefKey] of Object.entries(fields)) {
    const value = String(formData.get(formKey) || "").trim();
    if (value) brief[briefKey] = value;
  }
  return brief;
}
async function refineRunFromAnswers(form) {
  const run = state.detailRun;
  if (!run || form.dataset.refineRun !== run.id) return;
  const questions = Array.isArray(run.result?.clarifying_questions) ? run.result.clarifying_questions.slice(0, 5) : [];
  const answers = $$('[data-scope-answer]', form).map((field) => ({
    index: Number(field.dataset.scopeAnswer),
    answer: field.value.trim(),
  })).filter((item) => item.answer);
  if (!answers.length) {
    toast("Answer at least one scope question before starting a refined search.", "error");
    return;
  }
  const additions = answers.map(({ index, answer }) => `Question: ${questions[index]}\nUser answer: ${answer}`).join("\n\n");
  const maximum = 12000;
  const previous = String(run.brief?.clarification_answers || "").trim();
  const preservedPrevious = previous.slice(-Math.max(0, maximum - additions.length - 2));
  const brief = { ...(run.brief || {}), clarification_answers: [preservedPrevious, additions].filter(Boolean).join("\n\n").slice(-maximum) };
  const button = form.querySelector('[type="submit"]');
  if (button) { button.disabled = true; button.textContent = "Starting refined search…"; }
  const started = await startRun(run.question, run.project_id, [], brief, form);
  if (!started && button?.isConnected) {
    button.disabled = false;
    button.innerHTML = 'Start refined search <span class="button-arrow">→</span>';
  }
}
async function startRun(question, projectId, webUrls = [], brief = {}, sourceForm = null) {
  const trimmed = question.trim();
  if (trimmed.length < 8) { toast("Add a little more detail to your research question.", "error"); return; }
  try {
    state.projectId = projectId || state.projectId;
    const run = await api("/api/runs", { method: "POST", body: JSON.stringify({ question: trimmed, project_id: projectId || state.projectId, web_urls: webUrls.filter(Boolean).slice(0, 3), brief }) });
    state.activeRunId = run.id;
    sourceForm?.reset();
    if ($("#run-dialog").open) $("#run-dialog").close();
    toast("Your research team is getting started.");
    await loadDashboard();
    await loadRunDetail(run.id);
    return run;
  } catch (error) { toast(`Could not start research: ${error.message}`, "error"); return null; }
}

$(".primary-nav").addEventListener("click", (event) => {
  const button = event.target.closest("[data-view]");
  if (button) switchView(button.dataset.view);
});
$(".brand").addEventListener("click", (event) => { event.preventDefault(); switchView("home"); });
$("#project-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-project]");
  if (button) openProject(button.dataset.project);
});
$("#project-select").addEventListener("change", (event) => { state.projectId = event.target.value || null; });
$$('[data-view="runs"], [data-view="agents"]').filter((button) => !button.classList.contains("nav-item")).forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
$("#project-new-run").addEventListener("click", () => {
  $("#run-dialog-form").elements.project_id.value = state.projectId || "";
  $("#run-dialog").showModal();
});
$("#help-button").addEventListener("click", () => $("#help-dialog").showModal());
$(".more-button").addEventListener("click", () => $("#help-dialog").showModal());
$("#help-open-system").addEventListener("click", () => { $("#help-dialog").close(); switchView("system"); });
$("#new-run-secondary").addEventListener("click", () => $("#run-dialog").showModal());
$("#research-form").addEventListener("submit", (event) => { event.preventDefault(); const formData = new FormData(event.currentTarget); startRun($("#research-question").value, state.projectId, [$("#research-url").value.trim()], collectBrief(formData), event.currentTarget); });
$("#agent-trace-prev").addEventListener("click", () => moveAgentTrace(-1));
$("#agent-trace-next").addEventListener("click", () => moveAgentTrace(1));
$("#agent-trace-pause").addEventListener("click", () => { state.agentTrace.paused = !state.agentTrace.paused; renderAgentTrace(); });
$("#agent-trace-progress").addEventListener("click", (event) => {
  const dot = event.target.closest("[data-trace-step]");
  if (!dot) return;
  state.agentTrace.index = Number(dot.dataset.traceStep);
  renderAgentTrace();
});
$("#agent-trace-content").addEventListener("click", (event) => {
  const button = event.target.closest("[data-open-trace-run]");
  if (button) loadRunDetail(button.dataset.openTraceRun);
});
$("#run-dialog-form").addEventListener("submit", (event) => { event.preventDefault(); const form = new FormData(event.currentTarget); const urls = String(form.get("web_urls") || "").split(/\r?\n/).map((url) => url.trim()).filter(Boolean).slice(0, 3); startRun(form.get("question"), form.get("project_id"), urls, collectBrief(form), event.currentTarget); });
$("#add-project").addEventListener("click", () => $("#project-dialog").showModal());
$("#project-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const project = await api("/api/projects", { method: "POST", body: JSON.stringify({ name: form.get("name"), topic: form.get("topic") }) });
    state.projectId = project.id;
    await loadProjects(); await loadDashboard();
    $("#project-dialog").close(); event.currentTarget.reset(); toast("Project created.");
    await openProject(project.id);
  } catch (error) { toast(`Could not create project: ${error.message}`, "error"); }
});
$("#library-search").addEventListener("input", (event) => schedulePaperSearch(event.target.value));
$("#add-papers").addEventListener("click", () => {
  if (!state.projectId) { toast("Create a project before adding research papers.", "error"); return; }
  $("#pdf-files").click();
});
$("#pdf-files").addEventListener("change", async (event) => {
  const files = [...event.target.files];
  if (!files.length) return;
  if (files.length > 3) { toast("Choose up to three PDFs per upload.", "error"); event.target.value = ""; return; }
  const payload = new FormData();
  files.forEach((file) => payload.append("files", file));
  try {
    const response = await fetch(`/api/projects/${encodeURIComponent(state.projectId)}/pdfs`, { method: "POST", body: payload });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || `Upload failed (${response.status})`);
    toast(`Added ${result.count} PDF${result.count === 1 ? "" : "s"} to this project's local evidence library.`);
    await Promise.all([loadPapers($("#library-search").value), loadDashboard()]);
    if (state.view === "analysis") {
      state.analysisPaperId = result.saved?.[0]?.id || state.analysisPaperId;
      await loadAnalysisPaperList();
    }
  } catch (error) { toast(error.message, "error"); }
  event.target.value = "";
});
$("#back-to-runs").addEventListener("click", () => switchView("runs"));
$("#run-detail-content").addEventListener("input", (event) => {
  if (!event.target.matches("[data-scope-answer]") || state.scopeRefinement.runId !== state.detailRunId) return;
  state.scopeRefinement.answers[Number(event.target.dataset.scopeAnswer)] = event.target.value;
});
$("#run-detail-content").addEventListener("submit", (event) => {
  if (!event.target.matches("[data-refine-run]")) return;
  event.preventDefault();
  refineRunFromAnswers(event.target);
});
$("#run-detail-content").addEventListener("click", async (event) => {
  const rerun = event.target.closest("[data-review-rerun]");
  if (rerun && state.detailRun) {
    const previous = state.detailRun;
    rerun.disabled = true;
    rerun.textContent = "Starting review…";
    const webUrls = (previous.papers || []).filter((paper) => paper.source === "Web page" && paper.url).map((paper) => paper.url).slice(0, 3);
    const started = await startRun(previous.question, previous.project_id, webUrls, previous.brief || {});
    if (!started && rerun.isConnected) { rerun.disabled = false; rerun.innerHTML = 'Run this review again <span class="button-arrow">→</span>'; }
    return;
  }
  if (event.target.closest("[data-review-model-settings]")) {
    openModelSettings();
    return;
  }
  const discuss = event.target.closest("[data-discuss-clarifier]");
  if (discuss && state.detailRun) {
    const question = state.detailRun.result?.clarifying_questions?.[Number(discuss.dataset.discussClarifier)];
    if (question) {
      const context = `Help me decide how to answer this scope question: “${question}”`;
      state.reportChat.draft = state.reportChat.draft ? `${state.reportChat.draft}\n${context}` : context;
      renderReportChat();
      $("#run-chat-root").scrollIntoView({ behavior: "smooth", block: "start" });
      setTimeout(() => { if (state.reportChat.runId === state.detailRunId) $("#report-chat-form textarea")?.focus(); }, 350);
    }
    return;
  }
  if (!event.target.closest("[data-jump-report-chat]")) return;
  $("#run-chat-root").scrollIntoView({ behavior: "smooth", block: "start" });
  setTimeout(() => $("#report-chat-form textarea")?.focus(), 350);
});
$("#run-chat-root").addEventListener("submit", (event) => {
  if (event.target.id !== "report-chat-form") return;
  event.preventDefault();
  sendReportChat(event.target.elements.message.value);
});
$("#run-chat-root").addEventListener("input", (event) => {
  if (event.target.name === "message") state.reportChat.draft = event.target.value;
});
$("#run-chat-root").addEventListener("keydown", (event) => {
  if (event.target.name === "message" && event.key === "Enter" && !event.shiftKey) {
    event.preventDefault(); sendReportChat(event.target.value);
  }
});
$("#run-chat-root").addEventListener("click", (event) => {
  const prompt = event.target.closest("[data-chat-suggestion]");
  if (prompt) { sendReportChat(prompt.dataset.chatSuggestion); return; }
  if (event.target.closest("[data-chat-retry]")) {
    state.reportChat.loaded = false; state.reportChat.loading = false; state.reportChat.error = "";
    loadReportChat(state.reportChat.runId, state.reportChat.ready, state.reportChat.citationTargets);
    return;
  }
  if (event.target.closest("[data-chat-connect]")) openModelSettings();
});
$("#system-check-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const previousId = state.systemStatus?.reports?.[0]?.id;
  button.disabled = true;
  button.innerHTML = "Checking your lab <span class=\"button-arrow\">◌</span>";
  $("#system-summary").innerHTML = `<div class="system-health-banner"><span class="system-health-icon">◌</span><div><strong>Systems Engineer is reviewing the lab</strong><span>Local model analysis is running in the background.</span></div></div>`;
  try {
    await api("/api/system/care", { method: "POST", body: "{}" });
    let completed = false;
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      const history = await api("/api/system/history");
      if (history.reports?.[0]?.id && history.reports[0].id !== previousId) {
        completed = true;
        renderSystemCare({ ...state.systemStatus, ...history });
        break;
      }
    }
    if (completed) { await loadSystemCare(); toast("System review complete."); }
    else toast("The local review is still running. Its result will appear in Reviews and repairs.", "info");
  } catch (error) { toast(`System check failed: ${error.message}`, "error"); }
  finally { button.disabled = false; button.innerHTML = "Run system check <span class=\"button-arrow\">→</span>"; }
});
$("#model-action").addEventListener("click", openModelSettings);
$("#workspace-home").addEventListener("click", () => switchView("home"));
$("#model-refresh").addEventListener("click", refreshModelOptions);
$("#model-select").addEventListener("change", updateSelectedModelMemory);
["research", "pdf", "chat"].forEach((role) => $(`#role-model-${role}`).addEventListener("change", renderModelRoleMemory));
$("#model-catalog-refresh").addEventListener("click", loadModelCatalog);
$("#runtime-connect").addEventListener("click", connectModelRuntime);
$("#model-runtime").addEventListener("change", () => {
  $("#runtime-url").value = $("#model-runtime").value === "ollama" ? "http://127.0.0.1:11434/v1" : "http://127.0.0.1:8080/v1";
  $("#runtime-status").textContent = `Connect to your local ${$("#model-runtime").value} server.`;
});
$$("[data-model-tab]").forEach((button) => button.addEventListener("click", () => activateModelTab(button.dataset.modelTab)));
$("#model-catalog").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-install-model]");
  if (!button) return;
  const model = button.dataset.installModel;
  button.disabled = true;
  try {
    await api("/api/models/pull", { method: "POST", body: JSON.stringify({ model }) });
    await watchModelDownload(model);
  } catch (error) {
    $("#model-catalog-status").textContent = error.message;
    await loadModelCatalog();
  }
});
$("#ollama-custom-pull").addEventListener("click", async () => {
  const input = $("#ollama-model-name");
  const model = input.value.trim();
  if (!model) { input.focus(); return; }
  const button = $("#ollama-custom-pull");
  button.disabled = true; button.textContent = "Starting…";
  try {
    await api("/api/models/pull", { method: "POST", body: JSON.stringify({ model }) });
    await watchModelDownload(model);
  } catch (error) {
    $("#model-catalog-status").textContent = error.message;
  } finally { button.disabled = false; button.textContent = "Download model"; }
});
async function runHFSearch() {
  const query = $("#hf-query").value.trim();
  if (query) await searchHuggingFace(query);
}
$("#hf-search-button").addEventListener("click", runHFSearch);
$("#hf-query").addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); runHFSearch(); }
});
$("#model-roles-save").addEventListener("click", saveModelRoleSettings);
$("#specter2-setup").addEventListener("click", startSpecter2Setup);
$("#specter2-enabled").addEventListener("change", (event) => setSpecter2Enabled(event.currentTarget.checked));
$("#model-dialog").addEventListener("close", () => {
  if (state.specter2Timer) { clearInterval(state.specter2Timer); state.specter2Timer = null; }
  if (state.modelUsageTimer) { clearInterval(state.modelUsageTimer); state.modelUsageTimer = null; }
});
$("#hf-results").addEventListener("click", (event) => {
  const button = event.target.closest("[data-hf-repo]");
  if (button) showHuggingFaceFiles(button.dataset.hfRepo);
});
$("#hf-files").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-hf-download]");
  if (!button || !state.hfRepo) return;
  button.disabled = true; button.textContent = "Starting…";
  try {
    await api("/api/models/huggingface/download", { method: "POST", body: JSON.stringify({ repo: state.hfRepo, filename: button.dataset.hfDownload }) });
    await refreshHuggingFaceDownloads();
  } catch (error) {
    toast(error.message, "error");
    button.disabled = false; button.textContent = "Download";
  }
});
$("#hf-query").addEventListener("keydown", (event) => {
  if (event.key === "Escape") { $("#hf-results").innerHTML = ""; $("#hf-files").innerHTML = ""; }
});
$("#model-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const select = $("#model-select");
  if (!select.value) return;
  const submit = event.currentTarget.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    const result = await api("/api/model", { method: "POST", body: JSON.stringify({ model: select.value }) });
    fillModelOptions(result);
    $("#model-label").textContent = `${state.modelRuntime} · ${result.selected_model}`;
    $("#model-dialog").close();
    toast(`Research runs will use ${result.selected_model}.`);
  } catch (error) {
    $("#model-picker-status").textContent = error.message;
  } finally { submit.disabled = !select.value; }
});
$$("[data-close]").forEach((button) => button.addEventListener("click", () => $(`#${button.dataset.close}`).close()));
$("#today-label").textContent = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(new Date()).toUpperCase();

const initialView = window.location.hash.slice(1);
if (["home", "discover", "library", "analysis", "runs", "agents", "system"].includes(initialView)) {
  switchView(initialView, { resetScroll: false, writeHash: false });
}

async function refresh() {
  await Promise.all([loadProjects(), loadModel(), loadDashboard()]);
  if (state.view === "project" && state.projectId) await loadProjectRuns(state.projectId);
  if (state.view === "detail" && state.detailRunId) await loadRunDetail(state.detailRunId, { background: true });
  if (state.view === "agents") await loadAgentTrace();
}
refresh();
setInterval(refresh, 4500);
setInterval(() => {
  if (state.view === "agents" && state.agentTrace.active && !state.agentTrace.paused && state.agentTrace.events.length > 1) moveAgentTrace(1);
}, 4800);
