/* Admin contrat : filtrage dynamique des clients finaux (selon l'ESN)
   et des options additionnelles (hors critères déjà dans la formule). */
(function () {
  "use strict";

  function parseMap(el, attr) {
    var raw = el && el.getAttribute(attr);
    if (!raw) return {};
    try { return JSON.parse(raw); } catch (e) { return {}; }
  }

  function byId(id) { return document.getElementById(id); }

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

  // --- Options additionnelles : masque les critères déjà inclus dans la formule ---
  var typeSel = byId("id_contract_type");
  var extraBox = byId("id_extra_features");
  if (typeSel && extraBox) {
    var typeMap = parseMap(typeSel, "data-features");
    function filterExtras() {
      var included = typeMap[typeSel.value] || [];
      var boxes = extraBox.querySelectorAll('input[type="checkbox"]');
      for (var i = 0; i < boxes.length; i++) {
        var li = boxes[i].closest("li") || boxes[i].parentElement;
        var hide = included.indexOf(parseInt(boxes[i].value, 10)) !== -1;
        if (li) li.style.display = hide ? "none" : "";
        if (hide) boxes[i].checked = false;
      }
    }
    typeSel.addEventListener("change", filterExtras);
    filterExtras();
  }
})();
