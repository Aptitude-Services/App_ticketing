// Formulaire SLA : les horaires ouvrés ne s'affichent qu'en couverture 8x5.
document.addEventListener("DOMContentLoaded", function () {
  var coverage = document.getElementById("id_coverage");
  var block = document.querySelector("fieldset.apt-8x5");
  if (!coverage || !block) return;
  function sync() {
    block.hidden = coverage.value !== "8x5";
  }
  coverage.addEventListener("change", sync);
  sync();
});
