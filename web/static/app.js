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
const ruleSender = document.getElementById("rule-sender");
const ruleCategory = document.getElementById("rule-category");
const ruleBank = document.getElementById("rule-bank");
const senderForm = document.getElementById("sender-form");
const deleteBtn = document.getElementById("delete-btn");

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
  fillSelect(ruleBank, ["SNB", "MobilyPay", "AlRajhi", "RiyadBank", "SAB", "Alinma"], ruleBank.value, "Keep current");
}

async function loadSummary() {
  const response = await fetch(`/api/summary?${filterParams().toString()}`);
  const data = await response.json();
  monthEl.textContent = sar(data.total_amount);
  monthCountEl.textContent = filterYear.value || filterMonth.value ? "for selected period" : "all imported time";
  totalEl.textContent = String(data.txn_count);
  totalCountEl.textContent = "matching filters";
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
      <td>${row.merchant || "—"}</td>
      <td>${row.transaction_type || "—"}</td>
      <td>${row.category || "Other"}</td>
      <td class="num">${row.amount == null ? "—" : sar(row.amount)}</td>
    </tr>`;
  }).join("");
}

async function showDetail(id) {
  currentTxnId = id;
  viewLedger.hidden = true;
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
    ["Card", transaction.card_last4 || "—"],
    ["Account", transaction.account_last4 || "—"],
    ["GUID", transaction.source_message_guid || "—"],
  ];
  detailGrid.innerHTML = fields.map(([label, value]) => `<dt>${label}</dt><dd>${value}</dd>`).join("");
  detailRaw.textContent = transaction.raw_message || "(no SMS body stored)";
  ruleSender.value = transaction.sender || "";
  ruleCategory.value = transaction.category || "";
  ruleBank.value = transaction.bank || "";
}

function showLedger() {
  currentTxnId = null;
  viewLedger.hidden = false;
  viewDetail.hidden = true;
}

function route() {
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
    await refresh();
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

senderForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await fetch("/api/sender-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sender: ruleSender.value,
      category: ruleCategory.value,
      bank: ruleBank.value,
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.error || "Could not save sender rule", true);
    return;
  }
  setStatus(`Saved category for sender ${ruleSender.value}. Future SMS from this sender will use it.`);
  if (currentTxnId) showDetail(currentTxnId);
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
