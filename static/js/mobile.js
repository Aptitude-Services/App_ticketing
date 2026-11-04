// Mobile : menu latéral de la console en tiroir, et enregistrement de l'application installable (PWA).
(function () {
  // --- Tiroir de navigation (console, petits écrans) ---
  var body = document.body;
  var toggle = document.querySelector("[data-drawer-toggle]");
  var backdrop = document.querySelector("[data-drawer-backdrop]");
  function setOpen(open) {
    body.classList.toggle("drawer-open", open);
    if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (toggle) toggle.addEventListener("click", function () { setOpen(!body.classList.contains("drawer-open")); });
  if (backdrop) backdrop.addEventListener("click", function () { setOpen(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setOpen(false); });
  document.querySelectorAll(".c-side a").forEach(function (a) { a.addEventListener("click", function () { setOpen(false); }); });

  // --- Installation de l'application ---
  var installBtn = document.querySelector("[data-install-app]");
  var deferred = null;
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    if (installBtn) installBtn.hidden = false;
  });
  if (installBtn) installBtn.addEventListener("click", function () {
    if (!deferred) return;
    deferred.prompt();
    deferred.userChoice.finally(function () { deferred = null; installBtn.hidden = true; });
  });
  window.addEventListener("appinstalled", function () { if (installBtn) installBtn.hidden = true; });

  // Le service worker n'est actif qu'en HTTPS avec un certificat reconnu (ou sur localhost).
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js", { scope: "/" }); });
  }
})();
