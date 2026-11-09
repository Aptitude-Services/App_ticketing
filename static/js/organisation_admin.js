/* Fiche organisation : n'afficher que les champs utiles au type choisi.
   Client ESN → « Clients finaux » ; client final → « ESN rattachées » ;
   Aptitude → ni rattachements ni secteur d'activité. */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";

  var kind = document.getElementById("id_kind");
  if (!kind) return;

  var rows = {
    sector: document.querySelector(".field-activity_sector"),
    endClients: document.querySelector(".field-end_clients"),
    partnerEsns: document.querySelector(".field-partner_esns"),
  };

  function show(row, visible) {
    if (row) row.hidden = !visible;
  }

  function apply() {
    var value = kind.value;
    show(rows.sector, value !== "aptitude");
    show(rows.endClients, value === "client");
    show(rows.partnerEsns, value === "end_client");
  }

  kind.addEventListener("change", apply);
  apply();
});
