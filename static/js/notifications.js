// Cloche de notifications : ouverture/fermeture, « tout marquer comme lu » sans recharger,
// et rafraîchissement du compteur toutes les 60 secondes (seulement quand l'onglet est visible).
(function () {
  var bells = Array.prototype.slice.call(document.querySelectorAll("[data-notif]"));
  if (!bells.length) return;
  var panelUrl = bells[0].dataset.panelUrl;
  var REFRESH_MS = 60000;

  function render(unread, html) {
    bells.forEach(function (bell) {
      var count = bell.querySelector("[data-notif-count]");
      count.textContent = unread > 99 ? "99+" : String(unread);
      count.hidden = !unread;
      var readAll = bell.querySelector("[data-notif-readall]");
      if (readAll) readAll.hidden = !unread;
      if (html !== undefined) bell.querySelector("[data-notif-items]").innerHTML = html;
    });
  }

  function refresh() {
    if (document.hidden) return;
    fetch(panelUrl, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) render(data.unread, data.html); })
      .catch(function () {});
  }

  bells.forEach(function (bell) {
    // Un seul panneau ouvert à la fois ; on rafraîchit le contenu à l'ouverture.
    bell.addEventListener("toggle", function () {
      if (!bell.open) return;
      bells.forEach(function (other) { if (other !== bell) other.open = false; });
      refresh();
    });
    var form = bell.querySelector("[data-notif-readall]");
    if (form) form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" },
                           credentials: "same-origin" })
        .then(function (r) { if (r.ok) refresh(); });
    });
  });

  // Fermer au clic à l'extérieur ou avec Échap.
  document.addEventListener("click", function (ev) {
    bells.forEach(function (bell) { if (bell.open && !bell.contains(ev.target)) bell.open = false; });
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape") return;
    bells.forEach(function (bell) { if (bell.open) { bell.open = false; bell.querySelector("summary").focus(); } });
  });

  setInterval(refresh, REFRESH_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
