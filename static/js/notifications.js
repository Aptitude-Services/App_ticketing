// Cloche de notifications : ouverture/fermeture, « tout marquer comme lu » sans recharger,
// et rafraîchissement toutes les 15 secondes (seulement quand l'onglet est visible).
// Une nouvelle notification s'annonce par un bandeau ; si elle concerne la page affichée
// (ticket, rapport), la page se met à jour d'elle-même, sauf si une saisie est en cours.
(function () {
  var bells = Array.prototype.slice.call(document.querySelectorAll("[data-notif]"));
  if (!bells.length) return;
  var panelUrl = bells[0].dataset.panelUrl;
  var REFRESH_MS = 15000;
  var seen = null; // identifiants déjà connus ; null tant que le premier relevé n'est pas fait

  function typing() {
    // Une saisie non envoyée ne doit jamais être perdue par un rechargement.
    return Array.prototype.some.call(document.querySelectorAll("textarea, input[type=text], input[type=file]"),
      function (el) { return el.type === "file" ? el.files && el.files.length : el.value !== el.defaultValue; });
  }

  function toast(text, href, action) {
    var old = document.querySelector(".notif-toast");
    if (old) old.remove();
    var box = document.createElement("div");
    box.className = "notif-toast";
    box.setAttribute("role", "status");
    var link = document.createElement("a");
    link.href = href;
    link.textContent = text;
    box.appendChild(link);
    if (action) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = action;
      btn.addEventListener("click", function () { location.reload(); });
      box.appendChild(btn);
    }
    var close = document.createElement("button");
    close.type = "button";
    close.className = "notif-toast-close";
    close.setAttribute("aria-label", "Fermer");
    close.textContent = "×";
    close.addEventListener("click", function () { box.remove(); });
    box.appendChild(close);
    document.body.appendChild(box);
  }

  function announce(fresh) {
    var known = seen;
    seen = {};
    (fresh || []).forEach(function (n) { seen[n.id] = true; });
    if (known === null) return; // premier relevé : rien de nouveau à signaler
    var news = (fresh || []).filter(function (n) { return !known[n.id]; });
    if (!news.length) return;
    var here = news.some(function (n) {
      try { return new URL(n.url, location.href).pathname === location.pathname; } catch (e) { return false; }
    });
    if (here && !typing()) { location.reload(); return; }
    var text = news[0].title + (news.length > 1 ? " (+" + (news.length - 1) + ")" : "");
    toast(text, news[0].url, here ? "Actualiser" : null);
  }

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
      .then(function (data) { if (data) { render(data.unread, data.html); announce(data.fresh); } })
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

  refresh(); // premier relevé : mémorise les notifications déjà là
  setInterval(refresh, REFRESH_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
