/* ============================================
   KEYZ INK — script.js
   ============================================ */

/* ============================================
   ⚠️ OWNER CONFIG — edit before going live
   ============================================
   PayFast needs a real merchant account. To get merchant_id / merchant_key:
   1. Sign up at https://www.payfast.co.za
   2. Go to Settings → Integration to find your Merchant ID and Merchant Key
   3. Paste them below and set mode to "live"

   Bookings are now saved to the backend (server.py) first — that's what
   powers the admin dashboard at /admin. The PayFast ITN webhook
   (server.py's /api/payfast/notify) then marks a booking "paid"
   automatically once a deposit lands, once this is hosted with a real
   public HTTPS URL. Until then, mark deposits "Paid" manually in /admin.
============================================ */
const PAYFAST_CONFIG = {
  mode: "sandbox", // change to "live" once real credentials are in and site is hosted
  merchant_id: "10000100",   // sandbox test ID — replace with your real Merchant ID
  merchant_key: "46f0cd694581a", // sandbox test key — replace with your real Merchant Key
  deposit_amount: "200.00",
  return_url: window.location.origin + window.location.pathname + "?payment=success",
  cancel_url: window.location.origin + window.location.pathname + "?payment=cancelled",
  notify_url: window.location.origin + "/api/payfast/notify"
};

const WHATSAPP_NUMBER = "27710995517";

document.addEventListener("DOMContentLoaded", () => {
  initHeader();
  initHamburger();
  initGallery();
  initLightbox();
  initBookingForm();
  setMinDate();
});

/* ---------- Header scroll state ---------- */
function initHeader() {
  const header = document.getElementById("siteHeader");
  const onScroll = () => {
    if (window.scrollY > 40) header.classList.add("scrolled");
    else header.classList.remove("scrolled");
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
}

/* ---------- Mobile hamburger menu ---------- */
function initHamburger() {
  const hamburger = document.getElementById("hamburger");
  const nav = document.getElementById("mainNav");

  hamburger.addEventListener("click", () => {
    const isOpen = nav.classList.toggle("open");
    hamburger.classList.toggle("open", isOpen);
    hamburger.setAttribute("aria-expanded", isOpen);
  });

  nav.querySelectorAll(".nav-link").forEach(link => {
    link.addEventListener("click", () => {
      nav.classList.remove("open");
      hamburger.classList.remove("open");
      hamburger.setAttribute("aria-expanded", "false");
    });
  });
}

/* ---------- Gallery (placeholder tattoo images) ---------- */
const GALLERY_IMAGES = [
  "images/g1.jpeg", "images/g2.jpeg", "images/g3.jpeg", "images/g4.jpeg",
  "images/g5.jpeg", "images/g6.jpeg", "images/g7.jpeg", "images/g8.jpeg",
  "images/g9.jpeg", "images/g10.jpeg", "images/g11.jpeg", "images/g12.jpeg",
  "images/g13.jpeg", "images/g14.jpeg", "images/g15.jpeg", "images/g16.jpeg",
];

let galleryIndex = 0;

function initGallery() {
  const masonry = document.getElementById("masonry");
  masonry.innerHTML = GALLERY_IMAGES.map((src, i) => `
    <div class="masonry-item" data-index="${i}">
      <img src="${src}" alt="Tattoo artwork ${i + 1}" loading="lazy">
    </div>
  `).join("");

  masonry.querySelectorAll(".masonry-item").forEach(item => {
    item.addEventListener("click", () => openLightbox(parseInt(item.dataset.index, 10)));
  });
}

/* ---------- Lightbox ---------- */
function initLightbox() {
  document.getElementById("lightboxClose").addEventListener("click", closeLightbox);
  document.getElementById("lightboxPrev").addEventListener("click", () => stepLightbox(-1));
  document.getElementById("lightboxNext").addEventListener("click", () => stepLightbox(1));
  document.getElementById("lightbox").addEventListener("click", (e) => {
    if (e.target.id === "lightbox") closeLightbox();
  });
  document.addEventListener("keydown", (e) => {
    const lightbox = document.getElementById("lightbox");
    if (!lightbox.classList.contains("open")) return;
    if (e.key === "Escape") closeLightbox();
    if (e.key === "ArrowLeft") stepLightbox(-1);
    if (e.key === "ArrowRight") stepLightbox(1);
  });
}

function openLightbox(index) {
  galleryIndex = index;
  document.getElementById("lightboxImg").src = GALLERY_IMAGES[galleryIndex];
  document.getElementById("lightbox").classList.add("open");
  document.body.style.overflow = "hidden";
}

function stepLightbox(dir) {
  galleryIndex = (galleryIndex + dir + GALLERY_IMAGES.length) % GALLERY_IMAGES.length;
  document.getElementById("lightboxImg").src = GALLERY_IMAGES[galleryIndex];
}

function closeLightbox() {
  document.getElementById("lightbox").classList.remove("open");
  document.body.style.overflow = "";
}

/* ---------- Booking form ---------- */
function setMinDate() {
  const dateInput = document.getElementById("date");
  const today = new Date().toISOString().split("T")[0];
  dateInput.setAttribute("min", today);
}

function initBookingForm() {
  const form = document.getElementById("bookingForm");
  const whatsappOnlyBtn = document.getElementById("whatsappOnlyBtn");
  const submitBtn = document.getElementById("submitBtn");
  const formNote = document.getElementById("formNote");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }
    const data = getFormData();

    submitBtn.disabled = true;
    submitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Saving booking...`;

    let bookingId = null;
    try {
      bookingId = await saveBookingToServer(data);
    } catch (err) {
      console.warn("Could not reach the booking server, continuing without it:", err);
    }

    sendWhatsAppMessage(data);
    setTimeout(() => redirectToPayFast(data, bookingId), 600);
  });

  whatsappOnlyBtn.addEventListener("click", async () => {
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }
    const data = getFormData();
    try {
      await saveBookingToServer(data);
    } catch (err) {
      console.warn("Could not reach the booking server, continuing without it:", err);
    }
    sendWhatsAppMessage(data, true);
  });
}

function getFormData() {
  return {
    fullName: document.getElementById("fullName").value.trim(),
    phone: document.getElementById("phone").value.trim(),
    email: document.getElementById("email").value.trim(),
    service: document.getElementById("serviceType").value,
    date: document.getElementById("date").value,
    time: document.getElementById("time").value,
    description: document.getElementById("description").value.trim()
  };
}

/* Saves the booking to server.py so it shows up in /admin.
   Returns the new booking's id (used to reconcile PayFast payments later). */
async function saveBookingToServer(data) {
  const res = await fetch("/api/bookings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
  if (!res.ok) throw new Error("Booking save failed: " + res.status);
  const result = await res.json();
  return result.id;
}

function sendWhatsAppMessage(data, sameTab) {
  const message =
`Hello KEYZ INK, I would like to book an appointment.

Name: ${data.fullName}
Service: ${data.service}
Date: ${data.date}
Time: ${data.time}
Description: ${data.description}`;

  const url = `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(message)}`;

  if (sameTab) {
    window.location.href = url;
  } else {
    window.open(url, "_blank", "noopener");
  }
}

function redirectToPayFast(data, bookingId) {
  const cfg = PAYFAST_CONFIG;
  const baseUrl = cfg.mode === "live"
    ? "https://www.payfast.co.za/eng/process"
    : "https://sandbox.payfast.co.za/eng/process";

  // m_payment_id encodes the booking id so server.py's ITN handler can
  // find and mark the right booking as paid: KEYZINK-<bookingId>-<timestamp>
  const mPaymentId = `KEYZINK-${bookingId ?? "0"}-${Date.now()}`;

  const payFastForm = document.createElement("form");
  payFastForm.method = "POST";
  payFastForm.action = baseUrl;

  const fields = {
    merchant_id: cfg.merchant_id,
    merchant_key: cfg.merchant_key,
    return_url: cfg.return_url,
    cancel_url: cfg.cancel_url,
    notify_url: cfg.notify_url,
    name_first: data.fullName,
    email_address: data.email,
    m_payment_id: mPaymentId,
    amount: cfg.deposit_amount,
    item_name: "KEYZ INK — Booking Deposit",
    item_description: `${data.service} deposit for ${data.date} ${data.time}`,
    custom_str1: data.phone,
    custom_str2: data.service,
    custom_str3: `${data.date} ${data.time}`
  };

  Object.entries(fields).forEach(([key, value]) => {
    if (!value) return;
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = key;
    input.value = value;
    payFastForm.appendChild(input);
  });

  document.body.appendChild(payFastForm);
  payFastForm.submit();
}
