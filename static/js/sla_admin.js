// Formulaire SLA : les horaires ouvrés ne s'affichent qu'en couverture 8x5,
// et l'on ne peut pas cocher plus de 5 jours ouvrés (même limite côté serveur).
document.addEventListener("DOMContentLoaded", function () {
  var MAX_DAYS = 5;
  var coverage = document.getElementById("id_coverage");
  var block = document.querySelector("fieldset.apt-8x5");
  if (!coverage || !block) return;
  var days = block.querySelectorAll('input[name="working_days"]');

  function syncBlock() {
    block.hidden = coverage.value !== "8x5";
  }

  function syncDays() {
    var checked = 0;
    days.forEach(function (box) { if (box.checked) checked++; });
    var full = checked >= MAX_DAYS;
    days.forEach(function (box) {
      box.disabled = full && !box.checked;
      box.parentElement.style.opacity = box.disabled ? "0.45" : "";
      box.parentElement.title = box.disabled ? "5 jours ouvrés au plus en 8x5" : "";
    });
  }

  coverage.addEventListener("change", syncBlock);
  days.forEach(function (box) { box.addEventListener("change", syncDays); });
  syncBlock();
  syncDays();
});
