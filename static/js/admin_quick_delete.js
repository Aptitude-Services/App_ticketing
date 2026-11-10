/* Administration : suppression rapide dans les listes.
   - une icône corbeille au bout de chaque ligne (ouvre la confirmation de suppression) ;
   - le menu « Action » + « Envoyer » remplacé par un bouton par action (dont « Supprimer la
     sélection »), actifs dès qu'une ligne est cochée.
   Affichés seulement si l'utilisateur a le droit de supprimer (action « delete_selected » proposée).
   La page de confirmation de Django est conservée : une suppression est définitive. */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";

  // Page de confirmation : le bouton « Oui, je suis sûr » prend le focus (Entrée suffit).
  var confirm = document.querySelector(".delete-confirmation form [type=submit]");
  if (confirm) confirm.focus();

  var form = document.getElementById("changelist-form");
  var select = form && form.querySelector('select[name="action"]');
  if (!select) return;
  var canDelete = !!select.querySelector('option[value="delete_selected"]');

  var TRASH = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
    + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/>'
    + '<path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>';

  // 1. Le menu « Action » + « Envoyer » est remplacé par un bouton par action,
  //    actif dès qu'une ligne est cochée.
  var actions = form.querySelector(".actions");
  if (actions) {
    var go = actions.querySelector('button[name="index"], input[name="index"]');
    var label = select.closest("label") || select;
    // Masqués par style : le CSS de l'administration impose un affichage à ces éléments.
    label.style.display = "none";
    if (go) go.style.display = "none";
    var buttons = [];
    Array.prototype.forEach.call(select.options, function (opt) {
      if (!opt.value) return;
      var isDelete = opt.value === "delete_selected";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "button quick-action" + (isDelete ? " quick-delete-selected" : "");
      btn.innerHTML = (isDelete ? TRASH + "<span>Supprimer la sélection</span>" : "<span></span>");
      if (!isDelete) btn.querySelector("span").textContent = opt.textContent.trim();
      btn.addEventListener("click", function () {
        if (btn.disabled) return;
        select.value = opt.value;
        form.submit(); // une suppression passe par la page de confirmation de Django
      });
      buttons.push(btn);
    });
    // Supprimer en dernier, à droite des autres actions
    buttons.sort(function (x, y) { return x.classList.contains("quick-delete-selected") - y.classList.contains("quick-delete-selected"); });
    var counter = actions.querySelector(".action-counter");
    buttons.forEach(function (btn) { actions.insertBefore(btn, counter || null); });
    var refresh = function () {
      var none = !form.querySelector("input.action-select:checked");
      buttons.forEach(function (btn) { btn.disabled = none; });
    };
    form.addEventListener("change", refresh);
    refresh();
  }
  // 2. Icônes au bout de chaque ligne : crayon (modifier) et corbeille (supprimer, si autorisé)
  var PENCIL = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
    + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/>'
    + '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
  var table = document.getElementById("result_list");
  if (!table) return;
  var headRow = table.querySelector("thead tr");
  if (headRow) {
    var th = document.createElement("th");
    th.className = "column-quick-delete";
    th.innerHTML = '<span class="sr-only">Actions</span>';
    headRow.appendChild(th);
  }
  table.querySelectorAll("tbody tr").forEach(function (row) {
    var td = document.createElement("td");
    td.className = "quick-delete";
    var change = row.querySelector('a[href*="/change/"]');
    if (change) {
      var name = (change.textContent || "").trim();
      var edit = document.createElement("a");
      edit.href = change.getAttribute("href");
      edit.className = "quick-edit";
      edit.title = "Modifier";
      edit.setAttribute("aria-label", "Modifier " + name);
      edit.innerHTML = PENCIL;
      td.appendChild(edit);
      if (canDelete) {
        var del = document.createElement("a");
        del.href = change.getAttribute("href").replace("/change/", "/delete/");
        del.className = "quick-trash";
        del.title = "Supprimer";
        del.setAttribute("aria-label", "Supprimer " + name);
        del.innerHTML = TRASH;
        td.appendChild(del);
      }
    }
    row.appendChild(td);
  });
});
