const API_BASE_URL =
  (window.DEVPULSE_CONFIG && window.DEVPULSE_CONFIG.API_BASE_URL) || window.location.origin;

const state = {
  config: null,
  data: null,
  currentJobId: null,
  filters: {
    source: "all",
    risk: "all",
    relevanceMin: 0,
    search: "",
  },
  selectedSignalId: null,
};

const overviewCards = [
  { key: "total_signals", label: "Tổng tín hiệu", note: "Tổng tín hiệu đã lấy và chuẩn hóa" },
  { key: "high_relevance", label: "Liên quan cao", note: "Số tín hiệu có relevance score >= 70" },
  { key: "elevated_risks", label: "Rủi ro cao", note: "Số tín hiệu có risk level HIGH hoặc CRITICAL" },
  {
    key: "sources_active",
    label: "Nguồn hoạt động",
    note: "Các nguồn đang có dữ liệu thực tế",
    formatter: (stats) => Object.keys(stats.source_counts || {}).join(", "),
  },
];

function byId(id) {
  return document.getElementById(id);
}

async function fetchJSON(path, options) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-US").format(value || 0);
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function selectedSignal() {
  return (state.data?.signals || []).find((signal) => signal.id === state.selectedSignalId) || null;
}

function priorityScore(signal) {
  const relevance = Number(signal.relevance?.score || 0);
  const risk = Number(signal.risk?.risk_score || 0);
  return Math.round(0.65 * relevance + 0.35 * risk);
}

function sourceTags(signal) {
  const metadata = signal.metadata || {};
  const tags = [];
  if (Array.isArray(metadata.topics)) tags.push(...metadata.topics.slice(0, 3));
  if (Array.isArray(metadata.tags)) tags.push(...metadata.tags.slice(0, 3));
  if (metadata.language) tags.push(metadata.language);
  if (metadata.pipeline_tag) tags.push(metadata.pipeline_tag);
  if (metadata.primary_category) tags.push(metadata.primary_category);
  return [...new Set(tags)].slice(0, 4);
}

function riskBadgeClass(level) {
  switch ((level || "LOW").toUpperCase()) {
    case "CRITICAL":
      return "red";
    case "HIGH":
      return "amber";
    case "MEDIUM":
      return "purple";
    default:
      return "blue";
  }
}

function filteredSignals() {
  const search = state.filters.search.trim().toLowerCase();
  return (state.data?.signals || [])
    .filter((signal) => {
      if (state.filters.source !== "all" && signal.source !== state.filters.source) return false;
      if (state.filters.risk !== "all" && (signal.risk?.risk_level || "LOW").toUpperCase() !== state.filters.risk) {
        return false;
      }
      if ((signal.relevance?.score || 0) < state.filters.relevanceMin) return false;
      if (!search) return true;
      const text = `${signal.title} ${signal.description} ${signal.source}`.toLowerCase();
      return text.includes(search);
    })
    .sort((a, b) => priorityScore(b) - priorityScore(a));
}

function renderOverview() {
  const container = byId("overviewCards");
  const template = document.getElementById("overviewCardTemplate");
  container.innerHTML = "";

  const stats = state.data?.stats || {
    total_signals: 0,
    high_relevance: 0,
    elevated_risks: 0,
    source_counts: {},
  };

  overviewCards.forEach((card) => {
    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".overview-label").textContent = card.label;
    const value = card.formatter ? card.formatter(stats) : formatNumber(stats[card.key]);
    node.querySelector(".overview-value").textContent = value || "0";
    node.querySelector(".overview-note").textContent = card.note;
    container.appendChild(node);
  });
}

function renderPipeline() {
  const container = byId("pipelineStatus");
  container.innerHTML = "";
  safeArray(state.data?.pipeline_steps || []).forEach((step) => {
    const node = document.createElement("div");
    node.className = "status-node";
    node.innerHTML = `
      <div class="step-label">${step.label}</div>
      <div class="step-state step-${step.status}">${step.status.toUpperCase()}</div>
    `;
    container.appendChild(node);
  });
}

function renderProgress() {
  const percent = state.data?.progress_percent || 0;
  const message = state.data?.progress_message || "Đang chờ chạy pipeline.";
  const detail = state.data?.progress_detail || "Chưa có hoạt động nào.";
  const logs = state.data?.progress_logs || [];

  byId("progressPercent").textContent = `${percent}%`;
  byId("progressMessage").textContent = message;
  byId("progressDetail").textContent = detail;
  byId("progressFill").style.width = `${percent}%`;

  const logContainer = byId("progressLog");
  logContainer.innerHTML = "";
  if (!logs.length) {
    logContainer.innerHTML =
      '<div class="progress-log-item"><strong>Chưa có log</strong><span>Pipeline chưa bắt đầu hoặc chưa phát sinh mốc tiến trình nào.</span></div>';
    return;
  }

  [...logs].reverse().forEach((entry) => {
    const item = document.createElement("div");
    item.className = "progress-log-item";
    const timeText = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString("vi-VN") : "";
    item.innerHTML = `
      <strong>${entry.message || "Đang xử lý"}</strong>
      <span>${entry.detail || ""}</span>
      <span>${timeText} · ${entry.percent || 0}%</span>
    `;
    logContainer.appendChild(item);
  });
}

function renderTable() {
  const body = byId("signalsTableBody");
  body.innerHTML = "";
  const signals = filteredSignals();
  const total = state.data?.signals?.length || 0;
  byId("tableMeta").textContent = `${signals.length} / ${total} tín hiệu đang hiển thị`;

  if (!signals.length) {
    body.innerHTML = `
      <tr>
        <td colspan="6">
          <div class="detail-empty">Không có signal nào khớp bộ lọc hiện tại.</div>
        </td>
      </tr>
    `;
    return;
  }

  signals.forEach((signal) => {
    const tr = document.createElement("tr");
    if (signal.id === state.selectedSignalId) tr.classList.add("active");
    tr.innerHTML = `
      <td class="title-cell">
        <div class="title-main">${signal.title}</div>
        <div class="title-sub">${(signal.description || "Không có mô tả.").slice(0, 120)}</div>
      </td>
      <td><span class="badge blue">${signal.source}</span></td>
      <td><span class="badge teal">${signal.relevance?.score || 0}</span></td>
      <td><span class="badge ${riskBadgeClass(signal.risk?.risk_level)}">${signal.risk?.risk_level || "LOW"}</span></td>
      <td><div class="tag-list">${sourceTags(signal).map((tag) => `<span class="tag">${tag}</span>`).join("")}</div></td>
      <td>${signal.display_date || "-"}</td>
    `;
    tr.addEventListener("click", () => {
      state.selectedSignalId = signal.id;
      renderTable();
      renderDetail();
    });
    body.appendChild(tr);
  });
}

function renderDetail() {
  const signal = selectedSignal();
  const empty = byId("detailEmpty");
  const content = byId("detailContent");
  if (!signal) {
    empty.classList.remove("hidden");
    content.classList.add("hidden");
    return;
  }

  empty.classList.add("hidden");
  content.classList.remove("hidden");
  byId("detailSource").textContent = signal.source;
  byId("detailTitle").textContent = signal.title;
  byId("detailUrl").href = signal.url;
  byId("detailDescription").textContent = signal.description || "Không có mô tả.";
  byId("detailRelevance").textContent = `${signal.relevance?.score || 0}`;
  byId("detailRisk").textContent = `${signal.risk?.risk_level || "LOW"} / ${signal.risk?.risk_score || 0}`;
  byId("detailRelevanceReason").textContent = signal.relevance?.reasoning || "Không có giải thích.";
  byId("detailAction").textContent = signal.recommended_action || "Không có đề xuất.";

  const riskReason = byId("detailRiskReason");
  riskReason.innerHTML = "";
  safeArray(signal.risk?.concerns).forEach((concern) => {
    const item = document.createElement("div");
    item.className = "detail-list-item";
    item.textContent = concern;
    riskReason.appendChild(item);
  });
  if (!riskReason.children.length) {
    riskReason.innerHTML = '<div class="detail-list-item">Không có cảnh báo cụ thể.</div>';
  }

  const metadataGrid = byId("detailMetadata");
  metadataGrid.innerHTML = "";
  Object.entries(signal.metadata || {})
    .slice(0, 8)
    .forEach(([key, value]) => {
      const item = document.createElement("div");
      item.className = "metadata-item";
      item.innerHTML = `<span>${key}</span><strong>${String(value)}</strong>`;
      metadataGrid.appendChild(item);
    });
}

function renderDigest() {
  const digest = state.data?.digest || {};
  byId("digestSummary").textContent = digest.executive_summary || "Chưa có dữ liệu.";

  const topSignalsList = byId("topSignalsList");
  topSignalsList.innerHTML = "";
  safeArray(digest.priority_signals).slice(0, 5).forEach((signal) => {
    const item = document.createElement("div");
    item.className = "digest-item";
    item.innerHTML = `
      <strong>${signal.title}</strong>
      <span>Nguồn: ${signal.source} | Liên quan: ${signal.relevance?.score || 0} | Rủi ro: ${signal.risk?.risk_level || "LOW"}</span>
    `;
    topSignalsList.appendChild(item);
  });

  const riskSignals = filteredSignals().filter((signal) =>
    ["HIGH", "CRITICAL"].includes((signal.risk?.risk_level || "LOW").toUpperCase())
  );
  const risksList = byId("risksList");
  risksList.innerHTML = "";
  if (!riskSignals.length) {
    risksList.innerHTML =
      '<div class="digest-item"><strong>Không có rủi ro cao</strong><span>Không có tín hiệu HIGH/CRITICAL trong lần chạy này.</span></div>';
  } else {
    riskSignals.slice(0, 5).forEach((signal) => {
      const item = document.createElement("div");
      item.className = "digest-item";
      item.innerHTML = `
        <strong>${signal.title}</strong>
        <span>${safeArray(signal.risk?.concerns).join(" | ") || "Cần review thêm."}</span>
      `;
      risksList.appendChild(item);
    });
  }

  const actionsList = byId("actionsList");
  actionsList.innerHTML = "";
  safeArray(digest.recommendations).forEach((recommendation) => {
    const item = document.createElement("div");
    item.className = "digest-item";
    item.innerHTML = `<strong>Hành động</strong><span>${recommendation}</span>`;
    actionsList.appendChild(item);
  });
}

function exportDigest() {
  if (!state.data) return;
  const blob = new Blob([JSON.stringify(state.data.digest, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `devpulse-digest-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

async function pollJob(jobId) {
  while (true) {
    const job = await fetchJSON(`/api/job/${jobId}`);
    state.data = {
      ...(state.data || {}),
      pipeline_steps: job.pipeline_steps || [],
      progress_percent: job.progress_percent || 0,
      progress_message: job.message || "Đang chạy pipeline...",
      progress_detail:
        job.progress_logs && job.progress_logs.length
          ? job.progress_logs[job.progress_logs.length - 1].detail
          : job.message,
      progress_logs: job.progress_logs || [],
    };

    renderPipeline();
    renderProgress();
    byId("tableMeta").textContent = job.message || "Đang chạy pipeline...";

    if (job.status === "done" && job.result) {
      state.data = {
        ...job.result,
        progress_percent: 100,
        progress_message: "Pipeline hoàn tất",
        progress_detail: "Tất cả bước đã hoàn thành.",
        progress_logs: job.progress_logs || [],
      };
      const firstSignal = state.data.signals[0];
      state.selectedSignalId = firstSignal ? firstSignal.id : null;
      renderAll();
      byId("tableMeta").textContent = "Pipeline hoàn tất";
      return;
    }

    if (job.status === "failed") {
      byId("tableMeta").textContent = job.message || "Pipeline lỗi";
      byId("digestSummary").textContent = job.message || "Pipeline lỗi.";
      renderProgress();
      return;
    }

    await sleep(1200);
  }
}

async function runPipeline() {
  byId("tableMeta").textContent = "Đang khởi động pipeline...";
  const payload = {
    sources: state.config.sources.map((source) => source.key),
    signal_count: Number(byId("signalCount").value),
  };

  const job = await fetchJSON("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  state.currentJobId = job.job_id;
  state.data = {
    signals: [],
    digest: {},
    stats: {
      total_signals: 0,
      high_relevance: 0,
      elevated_risks: 0,
      source_counts: {},
    },
    pipeline_steps: [
      { key: "collect", label: "Thu thập", status: "pending" },
      { key: "relevance", label: "Liên quan", status: "pending" },
      { key: "risk", label: "Rủi ro", status: "pending" },
      { key: "synthesis", label: "Tổng hợp", status: "pending" },
      { key: "digest", label: "Bản tóm tắt", status: "pending" },
    ],
    progress_percent: 0,
    progress_message: "Đang khởi động pipeline...",
    progress_detail: "Tác vụ đã được gửi lên backend.",
    progress_logs: [],
  };
  renderAll();
  await pollJob(job.job_id);
}

function renderAll() {
  renderOverview();
  renderPipeline();
  renderProgress();
  renderTable();
  renderDetail();
  renderDigest();
}

function bindFilters() {
  byId("searchInput").addEventListener("input", (event) => {
    state.filters.search = event.target.value;
    renderTable();
    renderDigest();
  });

  byId("sourceFilter").addEventListener("change", (event) => {
    state.filters.source = event.target.value;
    renderTable();
    renderDigest();
  });

  byId("riskFilter").addEventListener("change", (event) => {
    state.filters.risk = event.target.value;
    renderTable();
    renderDigest();
  });

  byId("relevanceFilter").addEventListener("input", (event) => {
    state.filters.relevanceMin = Number(event.target.value);
    byId("relevanceValue").textContent = `${state.filters.relevanceMin}+`;
    renderTable();
    renderDigest();
  });
}

function populateSourceFilter() {
  const select = byId("sourceFilter");
  state.config.sources.forEach((source) => {
    const option = document.createElement("option");
    option.value = source.key;
    option.textContent = source.label;
    select.appendChild(option);
  });
}

function populateSignalCountOptions() {
  const select = byId("signalCount");
  select.innerHTML = "";
  const options = state.config.signal_count_options || [1, 2, 4, 8, 12, 16];
  options.forEach((value) => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = String(value);
    select.appendChild(option);
  });
}

async function init() {
  state.config = await fetchJSON("/api/config");
  populateSignalCountOptions();
  byId("signalCount").value = String(state.config.default_signal_count);
  populateSourceFilter();
  bindFilters();

  byId("runButton").addEventListener("click", runPipeline);
  byId("refreshButton").addEventListener("click", runPipeline);
  byId("exportButton").addEventListener("click", exportDigest);
}

init().catch((error) => {
  byId("digestSummary").textContent = `Không thể tải dashboard: ${error.message}`;
  byId("tableMeta").textContent = "Lỗi";
});
