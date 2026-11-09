/* Sélecteur de critères (admin) : compteurs par carte, résumé et recherche.
   Se met à jour à chaque changement, et sur l'événement « fc:refresh ». */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";

  function plural(n, one, many) { return n + " " + (n > 1 ? many : one); }

  function refresh(root) {
    var mode = root.getAttribute("data-mode");
    var query = (root.querySelector(".fc-filter") || {}).value || "";
    query = query.trim().toLowerCase();
    var totals = { all: 0, included: 0, chosen: 0 };
    var anyVisible = false;

    root.querySelectorAll(".fc-card").forEach(function (card) {
      var shown = 0, included = 0, chosen = 0, inCard = 0;
      card.querySelectorAll(".fc-row").forEach(function (row) {
        if (row.hidden) return; // masqué par la logique de la page (ex. formule)
        inCard++;
        var input = row.querySelector("input");
        var isIncluded = row.classList.contains("is-included");
        if (isIncluded) included++;
        else if (input && input.checked) chosen++;
        var match = !query || (row.getAttribute("data-search") || "").indexOf(query) !== -1;
        row.classList.toggle("fc-filtered", !match);
        if (match) shown++;
      });
      totals.all += inCard; totals.included += included; totals.chosen += chosen;
      card.classList.toggle("fc-card-hidden", shown === 0);
      if (shown) anyVisible = true;

      var count = card.querySelector(".fc-card-count");
      if (count) {
        count.textContent = mode === "contract"
          ? (included ? included + " incl." : "") + (included && chosen ? " · " : "") + (chosen ? "+" + chosen : "")
          : (chosen + included) + " / " + inCard;
        count.classList.toggle("is-active", chosen + included > 0);
      }
    });

    var empty = root.querySelector(".fc-empty");
    if (empty) empty.hidden = anyVisible;

    var summary = root.querySelector(".fc-summary");
    if (!summary) return;
    if (mode === "contract") {
      summary.innerHTML = "<strong>" + plural(totals.included, "critère inclus", "critères inclus")
        + "</strong> dans la formule · <strong>" + plural(totals.chosen, "supplément", "suppléments") + "</strong>";
    } else if (mode === "exclusions") {
      summary.innerHTML = "<strong>" + plural(totals.chosen, "critère retiré", "critères retirés") + "</strong>";
    } else {
      summary.innerHTML = "<strong>" + totals.chosen + "</strong> sur " + plural(totals.all, "critère", "critères")
        + " dans cette formule";
    }
  }

  var roots = document.querySelectorAll(".feature-checklist");
  function refreshAll() { roots.forEach(refresh); }

  roots.forEach(function (root) {
    root.addEventListener("change", function () { refresh(root); });
    var filter = root.querySelector(".fc-filter");
    if (filter) {
      filter.addEventListener("input", function () { refresh(root); });
      // Entrée dans la recherche ne doit pas soumettre le formulaire.
      filter.addEventListener("keydown", function (e) { if (e.key === "Enter") e.preventDefault(); });
    }
  });
  document.addEventListener("fc:refresh", refreshAll);
  refreshAll();
});
