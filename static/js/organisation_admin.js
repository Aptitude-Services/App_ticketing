/* Fiche organisation : n'afficher que les champs utiles au type choisi.
   Client ESN → « Clients finaux » ; client final → « ESN rattachées » ;
   Aptitude → ni rattachements ni secteur d'activité.
   Le secteur d'activité n'est demandé qu'au client final ; le logo qu'à l'ESN. */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";

  var kind = document.getElementById("id_kind");
  if (!kind) return;

  var rows = {
    sector: document.querySelector(".field-activity_sector"),
    logo: document.querySelector(".field-logo"),
    color: document.querySelector(".field-brand_color"),
    endClients: document.querySelector(".field-end_clients"),
    partnerEsns: document.querySelector(".field-partner_esns"),
  };

  function show(row, visible) {
    if (row) row.hidden = !visible;
  }

  function apply() {
    var value = kind.value;
    show(rows.sector, value === "end_client");
    show(rows.logo, value === "client");
    show(rows.color, value === "client");
    show(rows.endClients, value === "client");
    show(rows.partnerEsns, value === "end_client");
  }

  kind.addEventListener("change", apply);
  apply();

  // Aperçu immédiat du logo choisi, avant l'enregistrement.
  var logoInput = document.querySelector("[data-logo-input]");
  var preview = rows.logo && rows.logo.querySelector(".logo-preview");
  if (logoInput && preview && window.FileReader) {
    logoInput.addEventListener("change", function () {
      var file = logoInput.files && logoInput.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function (e) {
        preview.querySelector("img").src = e.target.result;
        preview.hidden = false;
      };
      reader.readAsDataURL(file);
    });
  }
});
