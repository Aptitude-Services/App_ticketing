/* Aides des champs : au lieu d'un texte affiché en permanence sous le champ, une petite
   icône « i » à côté du libellé ; le texte s'affiche au survol, au clic ou au clavier.
   Fonctionne sur les formulaires de l'application et de l'administration. */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";
  var seq = 0;

  function makeTip(text) {
    var tip = document.createElement("span");
    tip.className = "help-tip";
    tip.tabIndex = 0;
    tip.setAttribute("role", "button");
    tip.setAttribute("aria-label", text);
    tip.setAttribute("data-tip", text);
    tip.id = "help-tip-" + (++seq);
    tip.textContent = "i";
    tip.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      var open = tip.classList.toggle("is-open");
      document.querySelectorAll(".help-tip.is-open").forEach(function (t) { if (t !== tip) t.classList.remove("is-open"); });
      if (!open) tip.blur();
    });
    return tip;
  }

  document.addEventListener("click", function () {
    document.querySelectorAll(".help-tip.is-open").forEach(function (t) { t.classList.remove("is-open"); });
  });

  // Aide sous un champ : <div class="help"> dans une ligne de formulaire (application et admin).
  document.querySelectorAll(".form-row .help, .form-row div.help, .aligned .help").forEach(function (help) {
    if (help.closest(".help-keep") || help.tagName === "P" && help.id) return;
    var text = (help.textContent || "").replace(/\s+/g, " ").trim();
    var row = help.closest(".form-row");
    if (!row) return;
    // Libellé du champ : en ligne (case à cocher) ou au-dessus du champ.
    var label = help.closest("label") || row.querySelector("label:not(.check):not([for$='_0']), .flex-container > label, label");
    if (!text) { help.remove(); return; }
    if (!label) return;
    var host = label.querySelector(":scope > span") && label.classList.contains("check") ? label.querySelector(":scope > span") : label;
    host.appendChild(makeTip(text));
    help.remove();
  });
});
