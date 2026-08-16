const monthEl = document.getElementById("month-amount");
const monthCountEl = document.getElementById("month-count");
const totalEl = document.getElementById("total-amount");
const totalCountEl = document.getElementById("total-count");
const checkpointEl = document.getElementById("checkpoint");
const checkedAtEl = document.getElementById("checked-at");
const categoryBars = document.getElementById("category-bars");
const bankBars = document.getElementById("bank-bars");
const txnBody = document.getElementById("txn-body");
const filterBank = document.getElementById("filter-bank");
const filterCategory = document.getElementById("filter-category");
const syncBtn = document.getElementById("sync-btn");
const statusStrip = document.getElementById("status-strip");

function sar(value) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat("en-SA", {
    style: "currency",
    currency: "SAR",
    maximumFractionDigits: 2,
  }).format(amount);
}

function when(value) {
  if (!value) return "—";
  const date = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
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

function renderBars(target, rows, maxValue) {
  if (!rows.length) {
    target.innerHTML = '<p class="empty">No amounts yet.</p>';
    return;
  }
  target.innerHTML = rows
    .map((row) => {
      const width = maxValue ? Math.max(6, (Number(row.total_amount) / maxValue) * 100) : 0;
      return `<div class="bar-row">
        <div class="bar-meta"><span>${row.label}</span><span>${sar(row.total_amount)}</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
      </div>`;
    })
    .join("");
}

function fillSelect(select, values, current) {
  const keep = current || "";
  select.innerHTML = `<option value="">All</option>` + values
    .map((value) => `<option value="${value}"${value === keep ? " selected" : ""}>${value}</option>`)
    .join("");
}

async function loadSummary() {
  const response = await fetch("/api/summary");
  const data = await response.json();
  monthEl.textContent = sar(data.month_amount);
  monthCountEl.textContent = `${data.month_count} transactions this month`;
  totalEl.textContent = sar(data.total_amount);
  totalCountEl.textContent = `${data.txn_count} imported locally`;
  const checkpoint = (data.checkpoint && data.checkpoint[0]) || null;
  checkpointEl.textContent = checkpoint ? `#${checkpoint.last_message_id}` : "—";
  checkedAtEl.textContent = checkpoint && checkpoint.last_checked_at
    ? `checked ${when(checkpoint.last_checked_at)}`
    : "not synced";
  const catMax = Math.max(...data.by_category.map((row) => Number(row.total_amount) || 0), 0);
  const bankMax = Math.max(...data.by_bank.map((row) => Number(row.total_amount) || 0), 0);
  renderBars(categoryBars, data.by_category, catMax);
  renderBars(bankBars, data.by_bank, bankMax);
  fillSelect(filterBank, data.by_bank.map((row) => row.label), filterBank.value);
  fillSelect(filterCategory, data.by_category.map((row) => row.label), filterCategory.value);
}

async function loadTransactions() {
  const params = new URLSearchParams();
  if (filterBank.value) params.set("bank", filterBank.value);
  if (filterCategory.value) params.set("category", filterCategory.value);
  const response = await fetch(`/api/transactions?${params.toString()}`);
  const data = await response.json();
  const rows = data.transactions || [];
  if (!rows.length) {
    txnBody.innerHTML = `<tr><td colspan="6" class="empty">No bank transactions yet. Configure config/banks.json, then Sync Messages.</td></tr>`;
    return;
  }
  txnBody.innerHTML = rows
    .map((row) => `<tr>
      <td>${when(row.transaction_time || row.created_at)}</td>
      <td>${row.bank || "—"}</td>
      <td>${row.merchant || "—"}</td>
      <td>${row.transaction_type || "—"}</td>
      <td>${row.category || "Other"}</td>
      <td class="num">${row.amount == null ? "—" : sar(row.amount)}</td>
    </tr>`)
    .join("");
}

async function refresh() {
  await loadSummary();
  await loadTransactions();
}

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
    setStatus(`Synced. Scanned ${data.scanned}, stored ${data.stored}, ignored ${data.ignored_non_bank}.`);
    await refresh();
  } catch (error) {
    setStatus(String(error), true);
  } finally {
    syncBtn.disabled = false;
  }
});

filterBank.addEventListener("change", loadTransactions);
filterCategory.addEventListener("change", loadTransactions);

refresh().catch((error) => {
  txnBody.innerHTML = `<tr><td colspan="6" class="empty">${error}</td></tr>`;
});
