// Solutions d'un contrat : « Précision » seulement pour la catégorie Autre,
// dates de licence seulement pour Software et Cloud (même règle côté serveur).
(function () {
  var LICENSED = ["software", "cloud"];

  function toggle(cell, on) {
    if (!cell) return;
    cell.style.visibility = on ? "" : "hidden";
    cell.querySelectorAll("input, select").forEach(function (el) {
      if (!on) el.value = "";
    });
  }

  function syncRow(select) {
    var row = select.closest("tr");
    if (!row) return;
    var value = select.value;
    toggle(row.querySelector("td.field-other_category"), value === "other");
    var licensed = LICENSED.indexOf(value) !== -1;
    toggle(row.querySelector("td.field-license_start"), licensed);
    toggle(row.querySelector("td.field-license_end"), licensed);
  }

  function bind(select) {
    if (select.dataset.aptBound) return;
    select.dataset.aptBound = "1";
    select.addEventListener("change", function () { syncRow(select); });
    syncRow(select);
  }

  function bindAll(root) {
    root.querySelectorAll('select[name^="solutions-"][name$="-category"]').forEach(bind);
  }

  document.addEventListener("DOMContentLoaded", function () { bindAll(document); });
  // Lignes ajoutées avec « Ajouter un objet Solution supplémentaire ».
  document.addEventListener("formset:added", function (event) {
    bindAll(event.target && event.target.querySelectorAll ? event.target : document);
  });
})();
