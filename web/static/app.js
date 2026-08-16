const monthEl = document.getElementById("month-amount");
const monthCountEl = document.getElementById("month-count");
const totalEl = document.getElementById("total-amount");
const totalCountEl = document.getElementById("total-count");
const checkpointEl = document.getElementById("checkpoint");
const checkedAtEl = document.getElementById("checked-at");
const categoryBars = document.getElementById("category-bars");
const bankBars = document.getElementById("bank-bars");
const txnBody = document.getElementById("txn-body");
const filterYear = document.getElementById("filter-year");
const filterMonth = document.getElementById("filter-month");
const filterBank = document.getElementById("filter-bank");
const filterSender = document.getElementById("filter-sender");
const filterCategory = document.getElementById("filter-category");
const filterType = document.getElementById("filter-type");
const syncBtn = document.getElementById("sync-btn");
const dedupeBtn = document.getElementById("dedupe-btn");
const statusStrip = document.getElementById("status-strip");
const viewLedger = document.getElementById("view-ledger");
const viewDetail = document.getElementById("view-detail");
const detailGrid = document.getElementById("detail-grid");
const detailRaw = document.getElementById("detail-raw");
const detailAge = document.getElementById("detail-age");
const ruleMerchant = document.getElementById("rule-merchant");
const ruleCategory = document.getElementById("rule-category");
const merchantForm = document.getElementById("merchant-form");
const recurringAmountEl = document.getElementById("recurring-amount");
const recurringCountEl = document.getElementById("recurring-count");
const viewRecurring = document.getElementById("view-recurring");
const recurringBtn = document.getElementById("recurring-btn");
const recurringBars = document.getElementById("recurring-bars");
const recurringBody = document.getElementById("recurring-body");
const recurringPageMonth = document.getElementById("recurring-page-month");
const recurringPageYear = document.getElementById("recurring-page-year");
const recurringPageCount = document.getElementById("recurring-page-count");
const navLedger = document.getElementById("nav-ledger");
const navRecurring = document.getElementById("nav-recurring");
const navDashboard = document.getElementById("nav-dashboard");
const viewDashboard = document.getElementById("view-dashboard");
const dashYear = document.getElementById("dash-year");
const dashMonth = document.getElementById("dash-month");
const dashBank = document.getElementById("dash-bank");
const dashIncome = document.getElementById("dash-income");
const dashIncomeSub = document.getElementById("dash-income-sub");
const dashSpend = document.getElementById("dash-spend");
const dashSpendSub = document.getElementById("dash-spend-sub");
const dashNet = document.getElementById("dash-net");
const dashNetSub = document.getElementById("dash-net-sub");
const dashBalance = document.getElementById("dash-balance");
const dashBalanceSub = document.getElementById("dash-balance-sub");
const dashFlow = document.getElementById("dash-flow");
const dashDonut = document.getElementById("dash-donut");
const dashIncomeMix = document.getElementById("dash-income-mix");
const deleteBtn = document.getElementById("delete-btn");
const excludeBtn = document.getElementById("exclude-btn");

let filterCatalog = { years: [], banks: [], senders: [], categories: [], types: [], all_categories: [] };
let currentTxnId = null;

function sar(value) {
  return new Intl.NumberFormat("en-SA", {
    style: "currency",
    currency: "SAR",
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(String(value).replace(" ", "T"));
  return Number.isNaN(date.getTime()) ? null : date;
}

function when(value) {
  const date = parseDate(value);
  if (!date) return "—";
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function age(value) {
  const date = parseDate(value);
  if (!date) return "unknown age";
  const days = Math.max(0, Math.floor((Date.now() - date.getTime()) / 86400000));
  if (days === 0) return "today";
  if (days === 1) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} month${months === 1 ? "" : "s"} ago`;
  const years = Math.floor(days / 365);
  return `${years} year${years === 1 ? "" : "s"} ago`;
}

function setStatus(text, isError) {
  if (!text) {
    statusStrip.hidden = true;
    return;
  }
  statusStrip.hidden = false;
  statusStrip.textContent = text;
  statusStrip.classList.toggle("error", Boolean(isError));
}

function filterParams() {
  const params = new URLSearchParams();
  if (filterYear.value) params.set("year", filterYear.value);
  if (filterMonth.value) params.set("month", filterMonth.value);
  if (filterBank.value) params.set("bank", filterBank.value);
  if (filterSender.value) params.set("sender", filterSender.value);
  if (filterCategory.value) params.set("category", filterCategory.value);
  if (filterType.value) params.set("type", filterType.value);
  return params;
}

function fillSelect(select, values, current, blankLabel) {
  const keep = current || "";
  const options = [`<option value="">${blankLabel}</option>`]
    .concat(values.map((value) => `<option value="${value}"${value === keep ? " selected" : ""}>${value}</option>`));
  select.innerHTML = options.join("");
}

function renderColumnChart(target, rows) {
  if (!rows.length || rows.every((row) => !row.income && !row.spending)) {
    target.innerHTML = '<p class="empty">No income or spending in this period.</p>';
    return;
  }
  const width = 720;
  const height = 240;
  const left = 8;
  const right = 8;
  const top = 18;
  const bottom = 32;
  const innerW = width - left - right;
  const innerH = height - top - bottom;
  const max = Math.max(...rows.flatMap((row) => [Number(row.income) || 0, Number(row.spending) || 0]), 1);
  const groupW = innerW / rows.length;
  const barW = Math.max(4, groupW * 0.32);
  const columns = rows.map((row, index) => {
    const x = left + index * groupW + groupW * 0.18;
    const inH = ((Number(row.income) || 0) / max) * innerH;
    const outH = ((Number(row.spending) || 0) / max) * innerH;
    return `
      <rect class="col-in" x="${x}" y="${top + innerH - inH}" width="${barW}" height="${inH}"></rect>
      <rect class="col-out" x="${x + barW + 3}" y="${top + innerH - outH}" width="${barW}" height="${outH}"></rect>
      <text x="${x + barW}" y="${height - 10}" text-anchor="middle">${row.label}</text>
    `;
  }).join("");
  target.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Income versus spending by month">
    <line x1="${left}" y1="${top + innerH}" x2="${width - right}" y2="${top + innerH}" stroke="currentColor" stroke-opacity="0.25"></line>
    ${columns}
  </svg>`;
}

function renderDonut(target, rows) {
  if (!rows.length) {
    target.innerHTML = '<p class="empty">No spending to chart yet.</p>';
    return;
  }
  const colors = ["#c45c26", "#4f5d3c", "#16130f", "#8d3a12", "#cbbfa6", "#6d5a3c", "#2f3a28"];
  const total = rows.reduce((sum, row) => sum + Number(row.total_amount || 0), 0) || 1;
  const radius = 52;
  const circ = 2 * Math.PI * radius;
  let offset = 0;
  const rings = rows.map((row, index) => {
    const value = Number(row.total_amount || 0);
    const dash = (value / total) * circ;
    const slice = `<circle cx="70" cy="70" r="${radius}" fill="none" stroke="${colors[index % colors.length]}"
      stroke-width="18" stroke-dasharray="${dash} ${circ - dash}" stroke-dashoffset="${-offset}"></circle>`;
    offset += dash;
    return slice;
  }).join("");
  const legend = rows.map((row, index) => `
    <div><span><span class="donut-dot" style="background:${colors[index % colors.length]}"></span>${row.label}</span>
    <span>${sar(row.total_amount)}</span></div>
  `).join("");
  target.innerHTML = `<div class="donut-layout">
    <svg viewBox="0 0 140 140" role="img" aria-label="Spending by category">
      <circle cx="70" cy="70" r="${radius}" fill="none" stroke="rgba(22,19,15,0.08)" stroke-width="18"></circle>
      <g transform="rotate(-90 70 70)">${rings}</g>
      <text x="70" y="66" text-anchor="middle" font-size="9" fill="#4a4338">SPEND</text>
      <text x="70" y="82" text-anchor="middle" font-size="11" font-weight="600">${Math.round(total)}</text>
    </svg>
    <div class="donut-legend">${legend}</div>
  </div>`;
}

function renderBars(target, rows, maxValue) {
  if (!rows.length) {
    target.innerHTML = '<p class="empty">No amounts yet.</p>';
    return;
  }
  target.innerHTML = rows.map((row) => {
    const width = maxValue ? Math.max(6, (Number(row.total_amount) / maxValue) * 100) : 0;
    return `<div class="bar-row">
      <div class="bar-meta"><span>${row.label}</span><span>${sar(row.total_amount)}</span></div>
      <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
    </div>`;
  }).join("");
}

async function loadFilters() {
  const response = await fetch("/api/filters");
  filterCatalog = await response.json();
  fillSelect(filterYear, filterCatalog.years || [], filterYear.value, "All years");
  fillSelect(filterBank, filterCatalog.banks || [], filterBank.value, "All");
  fillSelect(filterSender, filterCatalog.senders || [], filterSender.value, "All");
  fillSelect(filterCategory, filterCatalog.categories || [], filterCategory.value, "All");
  fillSelect(filterType, filterCatalog.types || [], filterType.value, "All");
  fillSelect(ruleCategory, filterCatalog.all_categories || [], ruleCategory.value, "Choose category");
  fillSelect(dashYear, filterCatalog.years || [], dashYear.value, "All years");
  fillSelect(dashBank, filterCatalog.banks || [], dashBank.value, "All banks");
}

async function loadSummary() {
  const response = await fetch(`/api/summary?${filterParams().toString()}`);
  const data = await response.json();
  monthEl.textContent = sar(data.total_amount);
  monthCountEl.textContent = filterYear.value || filterMonth.value
    ? "spending in selected period"
    : "spending only · salary and incoming transfers excluded";
  totalEl.textContent = String(data.txn_count);
  totalCountEl.textContent = "matching filters";
  recurringAmountEl.textContent = sar(data.recurring_monthly);
  recurringCountEl.textContent = data.recurring_count
    ? `${data.recurring_count} monthly bill${data.recurring_count === 1 ? "" : "s"}`
    : "no monthly bills yet";
  const checkpoint = (data.checkpoint && data.checkpoint[0]) || null;
  checkpointEl.textContent = checkpoint ? `#${checkpoint.last_message_id}` : "—";
  checkedAtEl.textContent = checkpoint && checkpoint.last_checked_at
    ? `checked ${when(checkpoint.last_checked_at)}`
    : "not synced";
  const catMax = Math.max(...data.by_category.map((row) => Number(row.total_amount) || 0), 0);
  const bankMax = Math.max(...data.by_bank.map((row) => Number(row.total_amount) || 0), 0);
  renderBars(categoryBars, data.by_category, catMax);
  renderBars(bankBars, data.by_bank, bankMax);
}

async function loadTransactions() {
  const response = await fetch(`/api/transactions?${filterParams().toString()}`);
  const data = await response.json();
  const rows = data.transactions || [];
  if (!rows.length) {
    txnBody.innerHTML = `<tr><td colspan="8" class="empty">No matching transactions. Sync Messages or change filters.</td></tr>`;
    return;
  }
  txnBody.innerHTML = rows.map((row) => {
    const stamp = row.transaction_time || row.created_at;
    return `<tr data-id="${row.id}">
      <td>${when(stamp)}</td>
      <td>${age(stamp)}</td>
      <td>${row.bank || "—"}</td>
      <td>${row.sender || "—"}</td>
      <td>${row.merchant || "—"}${row.is_recurring ? ' <span class="badge">monthly</span>' : ""}</td>
      <td>${row.transaction_type || "—"}</td>
      <td>${row.category || "Other"}</td>
      <td class="num">${row.amount == null ? "—" : sar(row.amount)}</td>
    </tr>`;
  }).join("");
}

async function showDetail(id) {
  currentTxnId = id;
  hideViews();
  setNav("ledger");
  viewDetail.hidden = false;
  const response = await fetch(`/api/transactions/${id}`);
  if (!response.ok) {
    setStatus("Transaction not found", true);
    location.hash = "#/";
    return;
  }
  const { transaction } = await response.json();
  const stamp = transaction.transaction_time || transaction.created_at;
  detailAge.textContent = age(stamp);
  const fields = [
    ["When", when(stamp)],
    ["Age", age(stamp)],
    ["Bank", transaction.bank || "—"],
    ["Sender", transaction.sender || "—"],
    ["Merchant", transaction.merchant || "—"],
    ["Type", transaction.transaction_type || "—"],
    ["Category", transaction.category || "Other"],
    ["Amount", transaction.amount == null ? "—" : sar(transaction.amount)],
    ["Recurring", transaction.is_recurring ? "Yes · monthly bill" : "No"],
    ["Card", transaction.card_last4 || "—"],
    ["Account", transaction.account_last4 || "—"],
    ["GUID", transaction.source_message_guid || "—"],
  ];
  detailGrid.innerHTML = fields.map(([label, value]) => `<dt>${label}</dt><dd>${value}</dd>`).join("");
  detailRaw.textContent = transaction.raw_message || "(no SMS body stored)";
  ruleMerchant.value = transaction.merchant || "";
  ruleCategory.value = transaction.category || "";
  recurringBtn.textContent = transaction.is_recurring ? "Remove monthly bill" : "Mark as monthly bill";
  recurringBtn.disabled = ["salary", "bank_transfer_in"].includes(transaction.transaction_type);
}

function hideViews() {
  viewLedger.hidden = true;
  viewDetail.hidden = true;
  viewRecurring.hidden = true;
  viewDashboard.hidden = true;
}

function setNav(page) {
  navLedger.classList.toggle("active", page === "ledger");
  navRecurring.classList.toggle("active", page === "recurring");
  navDashboard.classList.toggle("active", page === "dashboard");
}

function showLedger() {
  currentTxnId = null;
  hideViews();
  setNav("ledger");
  viewLedger.hidden = false;
}

async function showDashboard() {
  currentTxnId = null;
  hideViews();
  setNav("dashboard");
  viewDashboard.hidden = false;
  await loadFilters();
  const params = new URLSearchParams();
  if (dashYear.value) params.set("year", dashYear.value);
  if (dashMonth.value) params.set("month", dashMonth.value);
  if (dashBank.value) params.set("bank", dashBank.value);
  const response = await fetch(`/api/dashboard?${params.toString()}`);
  const data = await response.json();
  dashIncome.textContent = sar(data.income);
  dashIncomeSub.textContent = `salary ${sar(data.salary)} · transfers in ${sar(data.transfers_in)}`;
  dashSpend.textContent = sar(data.spending);
  dashSpendSub.textContent = data.recurring_monthly
    ? `includes ${sar(data.recurring_monthly)} marked as monthly bills`
    : "outgoing transactions";
  dashNet.textContent = sar(data.net);
  dashNet.classList.toggle("net-neg", data.net < 0);
  dashNet.classList.toggle("net-pos", data.net >= 0);
  dashNetSub.textContent = data.net >= 0 ? "in minus spending" : "spent more than came in";
  if (data.latest_balance == null) {
    dashBalance.textContent = "—";
    dashBalanceSub.textContent = "no balance in SMS yet";
  } else {
    dashBalance.textContent = sar(data.latest_balance);
    dashBalanceSub.textContent = data.latest_balance_bank
      ? `${data.latest_balance_bank}${data.latest_balance_at ? " · " + when(data.latest_balance_at) : ""}`
      : "from the latest bank message";
  }
  renderColumnChart(dashFlow, data.by_month || []);
  renderDonut(dashDonut, data.by_category || []);
  renderBars(dashIncomeMix, [
    { label: "Salary", total_amount: data.salary },
    { label: "Incoming transfers", total_amount: data.transfers_in },
  ].filter((row) => Number(row.total_amount) > 0), Math.max(data.salary, data.transfers_in, 1));
}

async function showRecurring() {
  currentTxnId = null;
  hideViews();
  setNav("recurring");
  viewRecurring.hidden = false;
  const response = await fetch("/api/recurring");
  const data = await response.json();
  recurringPageMonth.textContent = sar(data.monthly_total);
  recurringPageYear.textContent = sar(data.yearly_total);
  recurringPageCount.textContent = data.item_count
    ? `${data.item_count} bill${data.item_count === 1 ? "" : "s"} you marked`
    : "mark a transaction as a monthly bill";
  const catMax = Math.max(...(data.by_category || []).map((row) => Number(row.total_amount) || 0), 0);
  renderBars(recurringBars, data.by_category || [], catMax);
  const rows = data.items || [];
  if (!rows.length) {
    recurringBody.innerHTML = `<tr><td colspan="4" class="empty">No monthly bills yet. Open a transaction and mark it.</td></tr>`;
    return;
  }
  recurringBody.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.label}</td>
      <td>${row.category || "Other"}</td>
      <td class="num">${sar(row.amount)}</td>
      <td><button class="btn btn-ghost" type="button" data-recurring-id="${row.id}">Remove</button></td>
    </tr>
  `).join("");
}

function route() {
  if (location.hash === "#/dashboard") {
    showDashboard();
    return;
  }
  if (location.hash === "#/recurring") {
    showRecurring();
    return;
  }
  const match = location.hash.match(/^#\/txn\/(\d+)/);
  if (match) {
    showDetail(match[1]);
    return;
  }
  showLedger();
  refresh();
}

async function refresh() {
  await loadFilters();
  await loadSummary();
  await loadTransactions();
}

txnBody.addEventListener("click", (event) => {
  const row = event.target.closest("tr[data-id]");
  if (row) location.hash = `#/txn/${row.dataset.id}`;
});

[filterYear, filterMonth, filterBank, filterSender, filterCategory, filterType].forEach((el) => {
  el.addEventListener("change", () => {
    loadSummary();
    loadTransactions();
  });
});

[dashYear, dashMonth, dashBank].forEach((el) => {
  el.addEventListener("change", () => {
    if (location.hash === "#/dashboard") showDashboard();
  });
});

syncBtn.addEventListener("click", async () => {
  syncBtn.disabled = true;
  setStatus("Reading Messages database in READ ONLY mode…");
  try {
    const response = await fetch("/api/sync", { method: "POST" });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      setStatus(data.error || "Sync failed", true);
      return;
    }
    setStatus(`Synced. Scanned ${data.scanned}, stored ${data.stored}, ignored ${data.ignored_non_bank}, skipped duplicates ${data.duplicates}.`);
    if (location.hash === "#/dashboard") await showDashboard();
    else if (location.hash === "#/recurring") await showRecurring();
    else await refresh();
  } catch (error) {
    setStatus(String(error), true);
  } finally {
    syncBtn.disabled = false;
  }
});

dedupeBtn.addEventListener("click", async () => {
  dedupeBtn.disabled = true;
  try {
    const response = await fetch("/api/duplicates/purge", { method: "POST" });
    const data = await response.json();
    setStatus(`Removed ${data.removed} duplicate transactions.`);
    await refresh();
  } catch (error) {
    setStatus(String(error), true);
  } finally {
    dedupeBtn.disabled = false;
  }
});

merchantForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await fetch("/api/merchant-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      merchant: ruleMerchant.value,
      category: ruleCategory.value,
      transaction_id: currentTxnId,
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.error || "Could not save merchant category", true);
    return;
  }
  const target = ruleMerchant.value || "this transaction";
  setStatus(`Saved category for ${target}. Matching merchants will use it from now on.`);
  if (currentTxnId) showDetail(currentTxnId);
});

recurringBtn.addEventListener("click", async () => {
  if (!currentTxnId) return;
  const isMonthly = recurringBtn.textContent.startsWith("Remove");
  const response = await fetch(`/api/transactions/${currentTxnId}/recurring`, {
    method: isMonthly ? "DELETE" : "POST",
  });
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.error || "Could not update recurring bill", true);
    return;
  }
  setStatus(isMonthly ? "Removed from monthly bills." : "Saved as a monthly bill. Open Recurring to see the total.");
  showDetail(currentTxnId);
});

recurringBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-recurring-id]");
  if (!button) return;
  const response = await fetch(`/api/recurring/${button.dataset.recurringId}`, { method: "DELETE" });
  if (!response.ok) {
    setStatus("Could not remove monthly bill", true);
    return;
  }
  setStatus("Removed from monthly bills.");
  showRecurring();
});

excludeBtn.addEventListener("click", async () => {
  if (!currentTxnId) return;
  const response = await fetch(`/api/transactions/${currentTxnId}/exclude`, { method: "POST" });
  if (!response.ok) {
    setStatus("Could not exclude this message", true);
    return;
  }
  setStatus("Excluded. This PIN/SMS will not be imported again.");
  location.hash = "#/";
});

deleteBtn.addEventListener("click", async () => {
  if (!currentTxnId) return;
  const response = await fetch(`/api/transactions/${currentTxnId}`, { method: "DELETE" });
  if (!response.ok) {
    setStatus("Could not delete transaction", true);
    return;
  }
  setStatus("Transaction deleted.");
  location.hash = "#/";
});

window.addEventListener("hashchange", route);
route();
