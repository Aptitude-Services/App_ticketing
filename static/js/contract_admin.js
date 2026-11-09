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

  // --- Clients finaux : liste des clients de l'ESN choisie ---
  // Les options sont reconstruites (et non simplement masquées) : une option
  // cachée reste sélectionnable au clavier sur certains navigateurs.
  var clientSel = byId("id_client");
  var endClientsSel = byId("id_end_clients");
  if (clientSel && endClientsSel) {
    var esnMap = parseMap(clientSel, "data-end-clients");
    var allOptions = Array.prototype.map.call(endClientsSel.options, function (o) {
      return { value: o.value, text: o.text, selected: o.selected };
    });
    var initialClient = clientSel.value;
    var hintEnd = document.createElement("p");
    hintEnd.className = "fc-hint";
    endClientsSel.parentNode.insertBefore(hintEnd, endClientsSel);
    function filterEndClients() {
      var allowed = clientSel.value ? (esnMap[clientSel.value] || []) : [];
      var keep = {};
      Array.prototype.forEach.call(endClientsSel.options, function (o) { keep[o.value] = o.selected; });
      endClientsSel.innerHTML = "";
      allOptions.forEach(function (o) {
        // Un client final déjà couvert reste affiché tant que l'ESN n'a pas changé.
        var historical = o.selected && clientSel.value === initialClient;
        if (allowed.indexOf(parseInt(o.value, 10)) === -1 && !historical) return;
        var opt = new Option(o.text, o.value);
        opt.selected = o.value in keep ? keep[o.value] : o.selected;
        endClientsSel.appendChild(opt);
      });
      endClientsSel.size = Math.min(Math.max(endClientsSel.options.length, 2), 8);
      if (!clientSel.value) hintEnd.textContent = "Choisissez d'abord l'ESN : la liste de ses clients finaux s'affichera ici.";
      else if (!endClientsSel.options.length) hintEnd.textContent = "Cette ESN n'a encore aucun client final rattaché.";
      else hintEnd.textContent = "Clients finaux de l'ESN choisie (Ctrl/Cmd + clic pour en sélectionner plusieurs).";
    }
    clientSel.addEventListener("change", filterEndClients);
    filterEndClients();
  }

  // --- Forfait de tickets : repris de la formule choisie ---
  // Le champ reste modifiable : une valeur saisie à la main n'est jamais écrasée
  // (on ne remplace que si le champ est vide ou contient la dernière valeur proposée).
  var formulaSel = byId("id_contract_type");
  var allowance = byId("id_allowance_tickets");
  if (formulaSel && allowance) {
    var allowances = parseMap(formulaSel, "data-allowances");
    var proposed = null;
    formulaSel.addEventListener("change", function () {
      if (!(formulaSel.value in allowances)) return;
      var value = allowances[formulaSel.value];
      var text = value === null ? "" : String(value);
      if (allowance.value === "" || allowance.value === proposed) {
        allowance.value = text;
        proposed = text;
      }
    });
    // Nouveau contrat déjà positionné sur une formule (ex. retour d'erreur) : on ne
    // touche pas à la saisie, mais on considère la valeur actuelle comme proposée
    // si elle correspond à la formule.
    if (formulaSel.value in allowances) {
      var current = allowances[formulaSel.value];
      if (allowance.value === (current === null ? "" : String(current))) proposed = allowance.value;
    }
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
