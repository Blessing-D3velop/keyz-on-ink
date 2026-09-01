
/* ============================================
   KEYZ INK — ADMIN DASHBOARD
   ============================================ */

const state = {
  bookings: [],
  filter: "",
  updating: new Set()
};


/* =========================================================
   START
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {

  wireLogin();
  wireLogout();
  wireFilters();
  wireModal();

  const refreshBtn = document.getElementById("refreshBtn");

  if (refreshBtn) {
    refreshBtn.addEventListener("click", loadEverything);
  }

  checkSession();

});


/* =========================================================
   AUTH — CHECK SESSION
   ========================================================= */

async function checkSession() {

  try {

    const res = await fetch("/api/admin/me", {
      credentials: "same-origin"
    });

    if (res.ok) {

      const data = await res.json();

      showApp(data.username);

    } else {

      showLogin();

    }

  } catch (error) {

    console.error("Session check failed:", error);

    showLogin();

  }

}


/* =========================================================
   SHOW LOGIN
   ========================================================= */

function showLogin() {

  const loginScreen = document.getElementById("loginScreen");
  const adminApp = document.getElementById("adminApp");

  if (loginScreen) {

    loginScreen.hidden = false;
    loginScreen.style.display = "flex";

  }

  if (adminApp) {

    adminApp.hidden = true;
    adminApp.style.display = "none";

  }

}


/* =========================================================
   SHOW ADMIN APP
   ========================================================= */

function showApp(username) {

  const loginScreen = document.getElementById("loginScreen");
  const adminApp = document.getElementById("adminApp");
  const whoami = document.getElementById("whoami");

  /*
     IMPORTANT:
     Completely hide the login screen.
  */

  if (loginScreen) {

    loginScreen.hidden = true;
    loginScreen.style.display = "none";

  }

  /*
     Show dashboard.
  */

  if (adminApp) {

    adminApp.hidden = false;
    adminApp.style.display = "block";

  }

  if (whoami) {

    whoami.textContent = username || "Admin";

  }

  loadEverything();

}


/* =========================================================
   LOGIN
   ========================================================= */

function wireLogin() {

  const form = document.getElementById("loginForm");
  const errorEl = document.getElementById("loginError");

  if (!form) return;

  form.addEventListener("submit", async (e) => {

    e.preventDefault();

    if (errorEl) {
      errorEl.textContent = "";
    }

    const username =
      document.getElementById("username").value.trim();

    const password =
      document.getElementById("password").value;

    const submitBtn =
      form.querySelector('button[type="submit"]');

    if (submitBtn) {

      submitBtn.disabled = true;
      submitBtn.textContent = "Logging in...";

    }

    try {

      const res = await fetch("/api/admin/login", {

        method: "POST",

        headers: {
          "Content-Type": "application/json"
        },

        credentials: "same-origin",

        body: JSON.stringify({
          username,
          password
        })

      });

      const data =
        await res.json().catch(() => ({}));


      /* ---------- LOGIN SUCCESS ---------- */

      if (res.ok) {

        form.reset();

        /*
          Hide login FIRST.
        */

        showApp(data.username);

        return;

      }


      /* ---------- LOGIN FAILED ---------- */

      if (errorEl) {

        errorEl.textContent =
          data.error || "Login failed.";

      }

    } catch (error) {

      console.error("Login error:", error);

      if (errorEl) {

        errorEl.textContent =
          "Unable to connect to the server.";

      }

    } finally {

      if (submitBtn) {

        submitBtn.disabled = false;
        submitBtn.textContent = "Log In";

      }

    }

  });

}


/* =========================================================
   LOGOUT
   ========================================================= */

function wireLogout() {

  const logoutBtn =
    document.getElementById("logoutBtn");

  if (!logoutBtn) return;

  logoutBtn.addEventListener("click", async () => {

    try {

      await fetch("/api/admin/logout", {

        method: "POST",

        credentials: "same-origin"

      });

    } catch (error) {

      console.error("Logout error:", error);

    }

    showLogin();

  });

}


/* =========================================================
   LOAD EVERYTHING
   ========================================================= */

async function loadEverything() {

  await Promise.all([
    loadStats(),
    loadBookings()
  ]);

}


/* =========================================================
   STATS
   ========================================================= */

async function loadStats() {

  try {

    const res = await fetch("/api/admin/stats", {
      credentials: "same-origin"
    });

    if (!res.ok) return;

    const s = await res.json();

    const total =
      document.getElementById("statTotal");

    const paid =
      document.getElementById("statPaid");

    const pending =
      document.getElementById("statPending");

    const revenue =
      document.getElementById("statRevenue");

    if (total) {
      total.textContent =
        s.total_bookings ?? 0;
    }

    if (paid) {
      paid.textContent =
        s.deposits_paid ?? 0;
    }

    if (pending) {
      pending.textContent =
        s.deposits_pending ?? 0;
    }

    if (revenue) {
      revenue.textContent =
        `R${Number(s.deposit_revenue || 0).toFixed(0)}`;
    }

  } catch (error) {

    console.error("Stats error:", error);

  }

}


/* =========================================================
   LOAD BOOKINGS
   ========================================================= */

async function loadBookings() {

  const tbody =
    document.getElementById("bookingsBody");

  try {

    const url = state.filter
      ? `/api/admin/bookings?status=${encodeURIComponent(state.filter)}`
      : "/api/admin/bookings";

    const res = await fetch(url, {
      credentials: "same-origin"
    });

    if (!res.ok) {

      if (tbody) {

        tbody.innerHTML = `
          <tr>
            <td colspan="8" class="empty-row">
              Unable to load bookings.
            </td>
          </tr>
        `;

      }

      return;

    }

    const data = await res.json();

    state.bookings =
      Array.isArray(data.bookings)
        ? data.bookings
        : [];

    renderBookings();

  } catch (error) {

    console.error("Bookings error:", error);

    if (tbody) {

      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="empty-row">
            Server connection error.
          </td>
        </tr>
      `;

    }

  }

}


/* =========================================================
   FILTERS
   ========================================================= */

function wireFilters() {

  const filterTabs =
    document.getElementById("filterTabs");

  if (!filterTabs) return;

  filterTabs.addEventListener("click", (e) => {

    const btn =
      e.target.closest(".filter-tab");

    if (!btn) return;

    document
      .querySelectorAll(".filter-tab")
      .forEach(tab => {
        tab.classList.remove("active");
      });

    btn.classList.add("active");

    state.filter =
      btn.dataset.filter || "";

    loadBookings();

  });

}


/* =========================================================
   PAYMENT BADGE
   ========================================================= */

function paymentBadge(status) {

  const map = {

    paid: ["badge-paid", "Paid"],

    pending: ["badge-pending", "Pending"],

    failed: ["badge-failed", "Failed"],

    cancelled: ["badge-cancelled", "Cancelled"]

  };

  const result =
    map[status] ||
    ["badge-pending", capitalize(status || "Unknown")];

  return `
    <span class="badge ${result[0]}">
      ${escapeHtml(result[1])}
    </span>
  `;

}


/* =========================================================
   RENDER BOOKINGS
   ========================================================= */

function renderBookings() {

  const tbody =
    document.getElementById("bookingsBody");

  if (!tbody) return;

  if (state.bookings.length === 0) {

    tbody.innerHTML = `
      <tr>
        <td colspan="8" class="empty-row">
          No bookings yet.
        </td>
      </tr>
    `;

    return;

  }


  tbody.innerHTML =
    state.bookings.map(b => {

      const cancelled =
        b.booking_status === "cancelled";

      const completed =
        b.booking_status === "completed";

      return `

        <tr
          data-id="${b.id}"
          class="${cancelled ? "booking-cancelled" : ""}"
        >

          <td>
            #${b.id}
          </td>


          <td>

            <span class="client-name">
              ${escapeHtml(b.full_name)}
            </span>

            ${
              b.description
                ? `
                  <span
                    class="client-desc-link"
                    data-action="view-desc"
                    data-id="${b.id}"
                  >
                    View description
                  </span>
                `
                : ""
            }

          </td>


          <td>

            <span class="contact-line">
              ${escapeHtml(b.phone)}
            </span>

            <span class="contact-line">
              ${escapeHtml(b.email)}
            </span>

          </td>


          <td>
            ${escapeHtml(b.service)}
          </td>


          <td>

            <span class="contact-line">
              ${escapeHtml(b.appt_date)}
            </span>

            <span class="contact-line">
              ${escapeHtml(b.appt_time)}
            </span>

          </td>


          <td>

            R${Number(b.deposit_amount || 0).toFixed(0)}

            <br>

            ${paymentBadge(b.payment_status)}

            ${
              b.payment_status !== "paid" &&
              !cancelled
                ? `
                  <button
                    type="button"
                    class="btn btn-tiny btn-primary"
                    style="margin-top:6px;"
                    data-action="mark-paid"
                    data-id="${b.id}"
                  >
                    Mark Paid
                  </button>
                `
                : ""
            }

          </td>


          <td>

            <select
              class="status-select"
              data-action="set-status"
              data-id="${b.id}"
            >

              ${
                ["new", "confirmed", "completed", "cancelled"]
                  .map(status => `
                    <option
                      value="${status}"
                      ${
                        b.booking_status === status
                          ? "selected"
                          : ""
                      }
                    >
                      ${capitalize(status)}
                    </option>
                  `)
                  .join("")
              }

            </select>

          </td>


          <td>

            <div class="row-actions">

              ${
                !cancelled && !completed
                  ? `
                    <button
                      type="button"
                      class="btn btn-tiny btn-danger"
                      title="Cancel booking"
                      data-action="cancel"
                      data-id="${b.id}"
                    >
                      <i class="fa-solid fa-xmark"></i>
                    </button>
                  `
                  : ""
              }


              ${
                cancelled
                  ? `
                    <button
                      type="button"
                      class="btn btn-tiny btn-ghost"
                      title="Restore booking"
                      data-action="restore"
                      data-id="${b.id}"
                    >
                      <i class="fa-solid fa-rotate-left"></i>
                    </button>
                  `
                  : ""
              }


              <button
                type="button"
                class="btn btn-tiny btn-ghost"
                title="Delete booking"
                data-action="delete"
                data-id="${b.id}"
              >
                <i class="fa-solid fa-trash"></i>
              </button>

            </div>

          </td>

        </tr>

      `;

    }).join("");


  wireBookingActions();

}


/* =========================================================
   BOOKING ACTIONS
   ========================================================= */

function wireBookingActions() {

  const tbody =
    document.getElementById("bookingsBody");

  if (!tbody) return;


  /* MARK PAID */

  tbody
    .querySelectorAll('[data-action="mark-paid"]')
    .forEach(btn => {

      btn.addEventListener("click", () => {

        updateBooking(
          btn.dataset.id,
          {
            payment_status: "paid"
          }
        );

      });

    });


  /* STATUS DROPDOWN */

  tbody
    .querySelectorAll('[data-action="set-status"]')
    .forEach(select => {

      select.addEventListener("change", async () => {

        const id =
          select.dataset.id;

        const status =
          select.value;


        if (status === "cancelled") {

          const confirmed =
            confirm(
              `Cancel booking #${id}?`
            );

          if (!confirmed) {

            await loadBookings();

            return;

          }

        }


        await updateBooking(
          id,
          {
            booking_status: status
          }
        );

      });

    });


  /* CANCEL BUTTON */

  tbody
    .querySelectorAll('[data-action="cancel"]')
    .forEach(btn => {

      btn.addEventListener("click", () => {

        const id =
          btn.dataset.id;

        const confirmed =
          confirm(
            `Cancel booking #${id}?\n\nThis will mark the booking as cancelled.`
          );

        if (!confirmed) return;

        updateBooking(
          id,
          {
            booking_status: "cancelled"
          }
        );

      });

    });


  /* RESTORE */

  tbody
    .querySelectorAll('[data-action="restore"]')
    .forEach(btn => {

      btn.addEventListener("click", () => {

        const id =
          btn.dataset.id;

        updateBooking(
          id,
          {
            booking_status: "new"
          }
        );

      });

    });


  /* DELETE */

  tbody
    .querySelectorAll('[data-action="delete"]')
    .forEach(btn => {

      btn.addEventListener("click", () => {

        deleteBooking(btn.dataset.id);

      });

    });


  /* DESCRIPTION */

  tbody
    .querySelectorAll('[data-action="view-desc"]')
    .forEach(el => {

      el.addEventListener("click", () => {

        showDescription(el.dataset.id);

      });

    });

}


/* =========================================================
   UPDATE BOOKING
   ========================================================= */

async function updateBooking(id, fields) {

  const key =
    String(id);

  if (state.updating.has(key)) {
    return;
  }

  state.updating.add(key);


  try {

    console.log(
      "Updating booking:",
      id,
      fields
    );


    const res =
      await fetch(
        `/api/admin/bookings/${id}`,
        {
          method: "PATCH",

          headers: {
            "Content-Type": "application/json"
          },

          credentials: "same-origin",

          body: JSON.stringify(fields)
        }
      );


    const data =
      await res.json().catch(() => ({}));


    if (!res.ok) {

      console.error(
        "Booking update failed:",
        res.status,
        data
      );

      alert(
        data.error ||
        `Could not update booking #${id}.`
      );

      return;

    }


    console.log(
      "Booking updated successfully:",
      data
    );


    await loadEverything();


  } catch (error) {

    console.error(
      "Booking update error:",
      error
    );

    alert(
      "Could not connect to the server."
    );


  } finally {

    state.updating.delete(key);

  }

}


/* =========================================================
   DELETE
   ========================================================= */

async function deleteBooking(id) {

  const confirmed =
    confirm(
      `Delete booking #${id}?\n\nThis cannot be undone.`
    );

  if (!confirmed) return;


  try {

    const res =
      await fetch(
        `/api/admin/bookings/${id}`,
        {
          method: "DELETE",
          credentials: "same-origin"
        }
      );


    const data =
      await res.json().catch(() => ({}));


    if (!res.ok) {

      alert(
        data.error ||
        `Could not delete booking #${id}.`
      );

      return;

    }


    await loadEverything();


  } catch (error) {

    console.error(
      "Delete error:",
      error
    );

    alert(
      "Could not connect to the server."
    );

  }

}


/* =========================================================
   MODAL
   ========================================================= */

function wireModal() {

  const closeBtn =
    document.getElementById("modalClose");

  const backdrop =
    document.getElementById("modalBackdrop");


  if (closeBtn) {

    closeBtn.addEventListener(
      "click",
      closeModal
    );

  }


  if (backdrop) {

    backdrop.addEventListener(
      "click",
      e => {

        if (
          e.target.id ===
          "modalBackdrop"
        ) {

          closeModal();

        }

      }
    );

  }


  document.addEventListener(
    "keydown",
    e => {

      if (e.key === "Escape") {
        closeModal();
      }

    }
  );

}


/* =========================================================
   DESCRIPTION MODAL
   ========================================================= */

function showDescription(id) {

  const booking =
    state.bookings.find(
      b =>
        String(b.id) ===
        String(id)
    );

  if (!booking) return;


  const title =
    document.getElementById("modalTitle");

  const body =
    document.getElementById("modalBody");

  const backdrop =
    document.getElementById("modalBackdrop");


  if (title) {

    title.textContent =
      `Booking #${booking.id} — ${booking.full_name}`;

  }


  if (body) {

    body.textContent =
      booking.description ||
      "No description provided.";

  }


  if (backdrop) {

    backdrop.hidden = false;

  }

}


function closeModal() {

  const backdrop =
    document.getElementById("modalBackdrop");

  if (backdrop) {

    backdrop.hidden = true;

  }

}


/* =========================================================
   UTILS
   ========================================================= */

function escapeHtml(str) {

  const div =
    document.createElement("div");

  div.textContent =
    str ?? "";

  return div.innerHTML;

}


function capitalize(str) {

  if (!str) return "";

  return (
    str.charAt(0).toUpperCase() +
    str.slice(1)
  );

}

