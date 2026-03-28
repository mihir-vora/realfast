const API = "";
const MEMBER_ID = "m-jane-smith";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── State ────────────────────────────────────────────────────────────────
let memberData = null;
let claimsData = [];

// ── Bootstrap ────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([loadMember(), loadClaims()]);
  wireForm();
});

// ── API helpers ──────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

// ── Member & Benefits ────────────────────────────────────────────────────
async function loadMember() {
  try {
    memberData = await api("GET", `/members/${MEMBER_ID}`);
    renderMember();
    renderBenefits();
  } catch (e) {
    toast("Failed to load member: " + e.message, true);
  }
}

function renderMember() {
  const m = memberData;
  const p = m.policy;
  $("#member-info").innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
      <div>
        <div style="font-size:1.1rem;font-weight:700">${m.name}</div>
        <div style="font-size:.82rem;color:var(--muted)">ID: ${m.id}</div>
      </div>
      ${p ? `<div style="text-align:right">
        <div style="font-size:.88rem;font-weight:600">${p.policy_number}</div>
        <div style="font-size:.78rem;color:var(--muted)">${p.effective_date} to ${p.end_date}</div>
        <div style="font-size:.82rem">Deductible: <span class="money">$${parseFloat(p.annual_deductible).toFixed(2)}</span></div>
      </div>` : ""}
    </div>`;
}

function renderBenefits() {
  const container = $("#benefits-list");
  if (!memberData.benefits.length) {
    container.innerHTML = '<div class="empty">No benefit data available</div>';
    return;
  }
  container.innerHTML = memberData.benefits.map(b => {
    const pct = b.limit > 0 ? Math.min(100, (parseFloat(b.used) / parseFloat(b.limit)) * 100) : 0;
    const cls = pct < 60 ? "ok" : pct < 85 ? "warn" : "danger";
    return `
      <div class="benefit">
        <div class="benefit-label">
          <span>${formatLabel(b.label)}</span>
          <span class="money">$${parseFloat(b.remaining).toFixed(2)} / $${parseFloat(b.limit).toFixed(2)}</span>
        </div>
        <div class="benefit-bar"><div class="benefit-fill ${cls}" style="width:${pct}%"></div></div>
      </div>`;
  }).join("");
}

// ── Claims List ──────────────────────────────────────────────────────────
async function loadClaims() {
  try {
    claimsData = await api("GET", "/claims");
    renderClaims();
  } catch (e) {
    toast("Failed to load claims: " + e.message, true);
  }
}

function renderClaims() {
  const tbody = $("#claims-tbody");
  if (!claimsData.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">No claims yet. Submit one above.</td></tr>';
    return;
  }
  tbody.innerHTML = claimsData.map(c => {
    const total = c.line_items.reduce((s, li) => s + parseFloat(li.amount_charged), 0);
    const approved = c.line_items.reduce((s, li) => s + parseFloat(li.amount_allowed), 0);
    const canAdj = c.status === "SUBMITTED";
    return `<tr>
      <td style="font-family:monospace;font-size:.78rem">${c.id.slice(0, 8)}...</td>
      <td>${c.provider}</td>
      <td>${c.line_items.length} item${c.line_items.length > 1 ? "s" : ""}</td>
      <td class="money">$${total.toFixed(2)}</td>
      <td><span class="status status-${c.status.toLowerCase()}">${c.status}</span></td>
      <td>
        ${canAdj ? `<button class="btn btn-primary btn-sm" onclick="adjudicateClaim('${c.id}')">Adjudicate</button>` : ""}
        <button class="btn btn-outline btn-sm" onclick="viewClaim('${c.id}')">Details</button>
      </td>
    </tr>`;
  }).join("");
}

// ── Claim Submission ─────────────────────────────────────────────────────
let lineItemCount = 0;

function wireForm() {
  $("#add-line-item").addEventListener("click", addLineItemRow);
  $("#claim-form").addEventListener("submit", handleSubmit);
  addLineItemRow();
}

function addLineItemRow() {
  lineItemCount++;
  const id = lineItemCount;
  const div = document.createElement("div");
  div.className = "li-row";
  div.id = `li-row-${id}`;
  div.innerHTML = `
    <div class="form-group">
      <label>Service</label>
      <select name="service_type_${id}" required>
        <option value="OFFICE_VISIT">Office Visit</option>
        <option value="LAB_WORK">Lab Work</option>
        <option value="IMAGING">Imaging</option>
        <option value="GENERIC_RX">Generic Rx</option>
        <option value="SPECIALIST">Specialist</option>
        <option value="EMERGENCY">Emergency</option>
      </select>
    </div>
    <div class="form-group">
      <label>Date</label>
      <input type="date" name="service_date_${id}" value="${todayStr()}" required>
    </div>
    <div class="form-group">
      <label>Amount ($)</label>
      <input type="number" name="amount_${id}" step="0.01" min="0.01" placeholder="150.00" required>
    </div>
    <button type="button" class="remove-li" onclick="removeLineItem(${id})" title="Remove">&times;</button>`;
  $("#line-items-container").appendChild(div);
}

window.removeLineItem = (id) => {
  const row = $(`#li-row-${id}`);
  if (row && $$("#line-items-container .li-row").length > 1) row.remove();
};

async function handleSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const submitBtn = $("#submit-btn");
  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span class="spinner"></span> Submitting...';

  try {
    const rows = $$("#line-items-container .li-row");
    const line_items = Array.from(rows).map(row => {
      const id = row.id.split("-")[2];
      return {
        service_type: row.querySelector(`[name="service_type_${id}"]`).value,
        service_date: row.querySelector(`[name="service_date_${id}"]`).value,
        amount_charged: parseFloat(row.querySelector(`[name="amount_${id}"]`).value),
      };
    });

    const payload = {
      member_id: MEMBER_ID,
      provider: $("#provider").value,
      diagnosis_code: $("#diagnosis").value,
      line_items,
    };

    const claim = await api("POST", "/claims", payload);
    toast(`Claim ${claim.id.slice(0, 8)} submitted`);
    form.reset();
    $("#line-items-container").innerHTML = "";
    lineItemCount = 0;
    addLineItemRow();
    await Promise.all([loadClaims(), loadMember()]);
  } catch (e) {
    toast(e.message, true);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Submit Claim";
  }
}

// ── Adjudicate ───────────────────────────────────────────────────────────
window.adjudicateClaim = async (claimId) => {
  const btn = event.target;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';

  try {
    const result = await api("POST", `/claims/${claimId}/adjudicate`);
    toast(`Claim adjudicated: ${result.status}`);
    await Promise.all([loadClaims(), loadMember()]);
    showAdjudicationResult(result);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Adjudicate";
  }
};

function showAdjudicationResult(result) {
  const panel = $("#detail-panel");
  panel.innerHTML = `
    <h3>Adjudication Result — ${result.claim_id.slice(0, 8)}...</h3>
    <div class="totals">
      <div class="item"><span class="label">Charged</span><span class="money">$${parseFloat(result.total_charged).toFixed(2)}</span></div>
      <div class="item"><span class="label">Approved</span><span class="money green">$${parseFloat(result.total_approved).toFixed(2)}</span></div>
      <div class="item"><span class="label">Member Owes</span><span class="money red">$${parseFloat(result.total_denied).toFixed(2)}</span></div>
      <div class="item"><span class="label">Status</span><span class="status status-${result.status.toLowerCase()}">${result.status}</span></div>
    </div>
    <div style="margin-top:16px">
      ${result.line_items.map(li => `
        <div class="explanation-card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <strong>${formatLabel(li.service_type)}</strong>
            <span class="status status-${li.status.toLowerCase()}">${li.status}</span>
          </div>
          <div class="member-msg">${li.explanation.member_explanation}</div>
          <div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border)">
            ${li.explanation.rule_trace.map(s => `<div class="trace-step">${s}</div>`).join("")}
          </div>
        </div>`).join("")}
    </div>`;
  panel.style.display = "block";
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── View Claim Detail ────────────────────────────────────────────────────
window.viewClaim = async (claimId) => {
  try {
    const claim = await api("GET", `/claims/${claimId}`);
    const panel = $("#detail-panel");
    const total = claim.line_items.reduce((s, li) => s + parseFloat(li.amount_charged), 0);
    const approved = claim.line_items.reduce((s, li) => s + parseFloat(li.amount_allowed), 0);

    panel.innerHTML = `
      <h3>Claim ${claim.id.slice(0, 8)}... — ${claim.provider}</h3>
      <div style="font-size:.82rem;color:var(--muted);margin-bottom:12px">
        Diagnosis: ${claim.diagnosis_code} &middot; Submitted: ${new Date(claim.submitted_at).toLocaleDateString()}
        &middot; Status: <span class="status status-${claim.status.toLowerCase()}">${claim.status}</span>
      </div>
      <table>
        <thead><tr><th>Service</th><th>Date</th><th>Charged</th><th>Approved</th><th>Status</th><th>Reason</th></tr></thead>
        <tbody>
          ${claim.line_items.map(li => `<tr>
            <td>${formatLabel(li.service_type)}</td>
            <td>${li.service_date}</td>
            <td class="money">$${parseFloat(li.amount_charged).toFixed(2)}</td>
            <td class="money ${li.amount_allowed > 0 ? 'green' : ''}">$${parseFloat(li.amount_allowed).toFixed(2)}</td>
            <td><span class="status status-${li.status.toLowerCase()}">${li.status}</span></td>
            <td style="font-size:.82rem">${li.denial_reason || "—"}</td>
          </tr>`).join("")}
        </tbody>
      </table>
      <div class="totals" style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px">
        <div class="item"><span class="label">Total Charged</span><span class="money">$${total.toFixed(2)}</span></div>
        <div class="item"><span class="label">Total Approved</span><span class="money green">$${approved.toFixed(2)}</span></div>
      </div>`;
    panel.style.display = "block";
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    toast(e.message, true);
  }
};

// ── Helpers ──────────────────────────────────────────────────────────────
function formatLabel(s) {
  return s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()).replace(/\bRx\b/gi, "Rx");
}

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast show" + (isError ? " error" : "");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => (el.className = "toast"), 3500);
}
