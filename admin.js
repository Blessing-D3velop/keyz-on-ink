/* ============================================
   KEYZ INK — admin.js
   ============================================ */

const state = {
  bookings: [],
  filter: "",
};

document.addEventListener("DOMContentLoaded", () => {
  wireLogin();
  wireLogout();
  wireFilters();
  wireModal();
  document.getElementById("refreshBtn").addEventListener("click", loadEverything);

  checkSession();
});

/* ---------- Auth ---------- */
async function checkSession() {
  const res = await fetch("/api/admin/me", { credentials: "same-origin" });
  if (res.ok) {
    const data = await res.json();
    showApp(data.username);
  } else {
    showLogin();
  }
}

function showLogin() {
  document.getElementById("loginScreen").hidden = false;
  document.getElementById("adminApp").hidden = true;
}

function showApp(username) {
  document.getElementById("loginScreen").hidden = true;
  document.getElementById("adminApp").hidden = false;
  document.getElementById("whoami").textContent = username;
  loadEverything();
}

function wireLogin() {
  const form = document.getElementById("loginForm");
  const errorEl = document.getElementById("loginError");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.textContent = "";

    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;

    const res = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ username, password }),
    });

    if (res.ok) {
      const data = await res.json();
      form.reset();
      showApp(data.username);
    } else {
      const data = await res.json().catch(() => ({}));
      errorEl.textContent = data.error || "Login failed.";
    }
  });
}

function wireLogout() {
  document.getElementById("logoutBtn").addEventListener("click", async () => {
    await fetch("/api/admin/logout", { method: "POST", credentials: "same-origin" });
    showLogin();
  });
}

/* ---------- Data loading ---------- */
async function loadEverything() {
  await Promise.all([loadStats(), loadBookings()]);
}

async function loadStats() {
  const res = await fetch("/api/admin/stats", { credentials: "same-origin" });
  if (!res.ok) return;
  const s = await res.json();
  document.getElementById("statTotal").textContent = s.total_bookings;
  document.getElementById("statPaid").textContent = s.deposits_paid;
  document.getElementById("statPending").textContent = s.deposits_pending;
  document.getElementById("statRevenue").textContent = `R${s.deposit_revenue.toFixed(0)}`;
}

async function loadBookings() {
  const url = state.filter
    ? `/api/admin/bookings?status=${encodeURIComponent(state.filter)}`
    : "/api/admin/bookings";
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) return;
  const data = await res.json();
  state.bookings = data.bookings;
  renderBookings();
}

/* ---------- Filters ---------- */
function wireFilters() {
  document.getElementById("filterTabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".filter-tab");
    if (!btn) return;
    document.querySelectorAll(".filter-tab").forEach(t => t.classList.remove("active"));
    btn.classList.add("active");
    state.filter = btn.dataset.filter;
    loadBookings();
  });
}

/* ---------- Render table ---------- */
function paymentBadge(status) {
  const map = {
    paid: ["badge-paid", "Paid"],
    pending: ["badge-pending", "Pending"],
    failed: ["badge-failed", "Failed"],
    cancelled: ["badge-cancelled", "Cancelled"],
  };
  const [cls, label] = map[status] || ["badge-pending", status];
  return `<span class="badge ${cls}">${label}</span>`;
}

function renderBookings() {
  const tbody = document.getElementById("bookingsBody");

  if (state.bookings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-row">No bookings yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = state.bookings.map(b => `
    <tr data-id="${b.id}">
      <td>#${b.id}</td>
      <td>
        <span class="client-name">${escapeHtml(b.full_name)}</span>
        ${b.description ? `<span class="client-desc-link" data-action="view-desc" data-id="${b.id}">View description</span>` : ""}
      </td>
      <td>
        <span class="contact-line">${escapeHtml(b.phone)}</span>
        <span class="contact-line">${escapeHtml(b.email)}</span>
      </td>
      <td>${escapeHtml(b.service)}</td>
      <td>
        <span class="contact-line">${escapeHtml(b.appt_date)}</span>
        <span class="contact-line">${escapeHtml(b.appt_time)}</span>
      </td>
      <td>
        R${b.deposit_amount.toFixed(0)}<br>
        ${paymentBadge(b.payment_status)}
        ${b.payment_status !== "paid" ? `<button class="btn btn-tiny btn-primary" style="margin-top:6px;" data-action="mark-paid" data-id="${b.id}">Mark Paid</button>` : ""}
      </td>
      <td>
        <select class="status-select" data-action="set-status" data-id="${b.id}">
          ${["new", "confirmed", "completed", "cancelled"].map(s =>
            `<option value="${s}" ${b.booking_status === s ? "selected" : ""}>${capitalize(s)}</option>`
          ).join("")}
        </select>
      </td>
      <td>
        <div class="row-actions">
          <button class="btn btn-tiny btn-ghost" data-action="delete" data-id="${b.id}"><i class="fa-solid fa-trash"></i></button>
        </div>
      </td>
    </tr>
  `).join("");

  tbody.querySelectorAll('[data-action="mark-paid"]').forEach(btn => {
    btn.addEventListener("click", () => updateBooking(btn.dataset.id, { payment_status: "paid" }));
  });
  tbody.querySelectorAll('[data-action="set-status"]').forEach(sel => {
    sel.addEventListener("change", () => updateBooking(sel.dataset.id, { booking_status: sel.value }));
  });
  tbody.querySelectorAll('[data-action="delete"]').forEach(btn => {
    btn.addEventListener("click", () => deleteBooking(btn.dataset.id));
  });
  tbody.querySelectorAll('[data-action="view-desc"]').forEach(el => {
    el.addEventListener("click", () => showDescription(el.dataset.id));
  });
}

/* ---------- Mutations ---------- */
async function updateBooking(id, fields) {
  const res = await fetch(`/api/admin/bookings/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(fields),
  });
  if (res.ok) {
    await loadEverything();
  }
}

async function deleteBooking(id) {
  if (!confirm(`Delete booking #${id}? This can't be undone.`)) return;
  const res = await fetch(`/api/admin/bookings/${id}`, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (res.ok) {
    await loadEverything();
  }
}

/* ---------- Modal ---------- */
function wireModal() {
  document.getElementById("modalClose").addEventListener("click", closeModal);
  document.getElementById("modalBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "modalBackdrop") closeModal();
  });
}

function showDescription(id) {
  const booking = state.bookings.find(b => String(b.id) === String(id));
  if (!booking) return;
  document.getElementById("modalTitle").textContent = `Booking #${booking.id} — ${booking.full_name}`;
  document.getElementById("modalBody").textContent = booking.description || "No description provided.";
  document.getElementById("modalBackdrop").hidden = false;
}

function closeModal() {
  document.getElementById("modalBackdrop").hidden = true;
}

/* ---------- Utils ---------- */
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function capitalize(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}
