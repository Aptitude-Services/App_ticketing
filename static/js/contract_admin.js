/* Admin contrat : filtrage dynamique des clients finaux (selon l'ESN)
   et des critères selon la formule choisie. */
/* L'admin charge ce script dans <head> : on attend que le formulaire existe. */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";

  function parseMap(el, attr) {
    var raw = el && el.getAttribute(attr);
    if (!raw) return {};
    try { return JSON.parse(raw); } catch (e) { return {}; }
  }

  function byId(id) { return document.getElementById(id); }

  function rowOf(el) { return el && (el.closest(".form-row") || el.parentElement); }

  // --- Clients finaux : limités à ceux rattachés à l'ESN choisie ---
  var clientSel = byId("id_client");
  var endClientsSel = byId("id_end_clients");
  if (clientSel && endClientsSel) {
    var esnMap = parseMap(clientSel, "data-end-clients");
    function filterEndClients() {
      var allowed = esnMap[clientSel.value];
      var opts = endClientsSel.options;
      for (var i = 0; i < opts.length; i++) {
        var show = !allowed || allowed.indexOf(parseInt(opts[i].value, 10)) !== -1;
        opts[i].hidden = !show;
        opts[i].style.display = show ? "" : "none";
        if (!show) opts[i].selected = false;
      }
    }
    clientSel.addEventListener("change", filterEndClients);
    filterEndClients();
  }

  // --- Critères : inclus (grisés, non cochables) / suppléments (cochables) ---
  var typeSel = byId("id_contract_type");
  var extraBox = byId("id_extra_features");
  var excludedBox = byId("id_excluded_features");
  if (!typeSel || !extraBox) return;

  var typeMap = parseMap(typeSel, "data-features");
  var hint = document.createElement("p");
  hint.className = "fc-hint";
  hint.textContent = "Choisissez d'abord une formule : ses critères s'afficheront comme inclus, "
    + "et vous pourrez activer des suppléments.";
  rowOf(extraBox).parentNode.insertBefore(hint, rowOf(extraBox));

  function boxes(container) {
    return container ? container.querySelectorAll('input[type="checkbox"]') : [];
  }

  function refreshSummaries() {
    document.dispatchEvent(new CustomEvent("fc:refresh"));
  }

  function applyFormula() {
    var chosen = !!typeSel.value;
    var included = typeMap[typeSel.value] || [];
    hint.hidden = chosen;
    rowOf(extraBox).hidden = !chosen;
    if (excludedBox) rowOf(excludedBox).hidden = !chosen;
    if (!chosen) return;

    boxes(extraBox).forEach(function (box) {
      var inc = included.indexOf(parseInt(box.value, 10)) !== -1;
      var label = box.closest(".fc-row");
      if (inc) {
        box.checked = true;
      } else if (box.dataset.included === "1") {
        box.checked = false; // était inclus dans l'ancienne formule : ce n'est pas un supplément
      }
      box.disabled = inc;
      box.dataset.included = inc ? "1" : "";
      if (label) label.classList.toggle("is-included", inc);
    });

    // Critères retirés : seuls ceux de la formule peuvent l'être.
    boxes(excludedBox).forEach(function (box) {
      var inc = included.indexOf(parseInt(box.value, 10)) !== -1;
      var label = box.closest(".fc-row");
      if (label) label.hidden = !inc;
      if (!inc) box.checked = false;
    });
    refreshSummaries();
  }

  typeSel.addEventListener("change", applyFormula);
  applyFormula();
});
