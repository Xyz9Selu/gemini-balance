/**
 * Model call stats dashboard - fetches and displays call counts per model
 * for Overall and Quota Cycle periods.
 */

async function fetchAPI(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || err.message || `HTTP ${response.status}`);
  }
  return response.json();
}

function getPeriodFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const p = params.get("period");
  return p === "overall" ? "overall" : "quota_cycle";
}

function setPeriodInUrl(period) {
  const url = new URL(window.location.href);
  url.searchParams.set("period", period);
  window.history.replaceState({}, "", url.toString());
}

function renderTable(rows) {
  const tbody = document.getElementById("statsTableBody");
  const emptyState = document.getElementById("emptyState");
  const contentState = document.getElementById("contentState");

  tbody.innerHTML = "";
  if (!rows || rows.length === 0) {
    document.querySelector(".model-stats-table").classList.add("hidden");
    emptyState.classList.remove("hidden");
    return;
  }

  document.querySelector(".model-stats-table").classList.remove("hidden");
  emptyState.classList.add("hidden");

  rows.forEach((r) => {
    const tr = document.createElement("tr");
    const avg = r.avg_per_key ?? 0;
    tr.innerHTML = `
      <td class="font-mono text-sm">${escapeHtml(r.model)}</td>
      <td class="text-right"><span class="stat-badge stat-total">${r.total}</span></td>
      <td class="text-right"><span class="stat-badge stat-total">${avg}</span></td>
      <td class="text-right"><span class="stat-badge stat-success">${r.success}</span></td>
      <td class="text-right"><span class="stat-badge stat-failed">${r.failed}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function updatePeriodTabs(period) {
  const tabs = document.querySelectorAll(".period-tab");
  tabs.forEach((t) => {
    const isActive = t.dataset.period === period;
    if (isActive) {
      t.style.backgroundColor = "#3b82f6";
      t.style.color = "#ffffff";
      t.style.borderWidth = "2px";
      t.style.borderColor = "#2563eb";
    } else {
      t.style.backgroundColor = "#f8fafc";
      t.style.color = "#64748b";
      t.style.borderWidth = "2px";
      t.style.borderColor = "#e2e8f0";
    }
  });
}

function showQuotaCycleInfo(quotaReset) {
  const info = document.getElementById("quotaCycleInfo");
  const text = document.getElementById("cycleStartText");
  if (!quotaReset || !quotaReset.cycle_start) {
    info.classList.add("hidden");
    return;
  }
  const start = new Date(quotaReset.cycle_start);
  const tz = quotaReset.timezone || "UTC";
  const hour = quotaReset.hour ?? 16;
  text.textContent = `配额周期自 ${start.toLocaleString("zh-CN", { timeZone: tz })} 起 (${tz}, 每日 ${hour}:00 重置)`;
  info.classList.remove("hidden");
}

function showLoading() {
  document.getElementById("loadingState").classList.remove("hidden");
  document.getElementById("contentState").classList.add("hidden");
  document.getElementById("errorState").classList.add("hidden");
}

function showContent() {
  document.getElementById("loadingState").classList.add("hidden");
  document.getElementById("contentState").classList.remove("hidden");
  document.getElementById("errorState").classList.add("hidden");
}

function showError(msg) {
  document.getElementById("loadingState").classList.add("hidden");
  document.getElementById("contentState").classList.add("hidden");
  document.getElementById("errorState").classList.remove("hidden");
  document.getElementById("errorMessage").textContent = msg;
}

function renderFromData(data, period) {
  const rows = period === "quota_cycle" ? data.quota_cycle : data.overall;
  renderTable(rows);
  if (period === "quota_cycle" && data.quota_reset) {
    showQuotaCycleInfo(data.quota_reset);
  } else {
    document.getElementById("quotaCycleInfo").classList.add("hidden");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const period = getPeriodFromUrl();
  setPeriodInUrl(period);
  updatePeriodTabs(period);

  showLoading();
  try {
    const data = await fetchAPI("/api/stats/model-call-stats");
    window.__modelStatsData = data;
    showContent();
    renderFromData(data, period);
  } catch (e) {
    showError(e.message || "加载失败");
  }

  // Tab click: switch period without reload
  document.querySelectorAll(".period-tab").forEach((tab) => {
    tab.addEventListener("click", (e) => {
      e.preventDefault();
      const newPeriod = tab.dataset.period;
      if (newPeriod === getPeriodFromUrl()) return;
      setPeriodInUrl(newPeriod);
      updatePeriodTabs(newPeriod);
      if (window.__modelStatsData) {
        renderFromData(window.__modelStatsData, newPeriod);
      }
    });
  });
});
