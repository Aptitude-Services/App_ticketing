/* Liste des organisations : déplier une ESN pour voir ses clients finaux.
   Le bouton « ▸ N » de la colonne « Clients finaux » porte la liste (data-children, JSON) ;
   un clic insère une ligne par client final sous l'ESN, un second clic les retire.
   Lancé après admin_quick_delete.js (chargé en « defer ») : la colonne d'icônes existe déjà. */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";

  var table = document.getElementById("result_list");
  if (!table) return;
  var canDelete = !!document.querySelector('#changelist-form select[name="action"] option[value="delete_selected"]');

  var PENCIL = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
    + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/>'
    + '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
  var TRASH = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
    + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/>'
    + '<path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>';

  // Index des colonnes d'après les classes « column-<champ> » de l'en-tête.
  var heads = Array.prototype.slice.call(table.querySelectorAll("thead th"));
  function col(name) {
    for (var i = 0; i < heads.length; i++) if (heads[i].classList.contains("column-" + name)) return i;
    return -1;
  }
  var COLS = { name: col("name"), code: col("code"), kind: col("kind"), sector: col("sector"),
               active: col("is_active"), domains: col("email_domains"), actions: col("quick-delete") };

  function text(td, value) { td.textContent = value || "—"; }

  function childRow(child) {
    var tr = document.createElement("tr");
    tr.className = "org-child-row";
    for (var i = 0; i < heads.length; i++) tr.appendChild(document.createElement("td"));
    var cells = tr.children;
    if (COLS.name >= 0) {
      var a = document.createElement("a");
      a.href = child.url;
      a.textContent = child.name;
      cells[COLS.name].className = "org-child-name";
      cells[COLS.name].appendChild(a);
    }
    if (COLS.code >= 0) text(cells[COLS.code], child.code);
    if (COLS.kind >= 0) text(cells[COLS.kind], child.kind);
    if (COLS.sector >= 0) text(cells[COLS.sector], child.sector);
    if (COLS.domains >= 0) text(cells[COLS.domains], child.domains);
    if (COLS.active >= 0) {
      var img = document.createElement("img");
      img.src = "/static/admin/img/icon-" + (child.active ? "yes" : "no") + ".svg";
      img.alt = child.active ? "True" : "False";
      cells[COLS.active].appendChild(img);
    }
    if (COLS.actions >= 0) {
      var td = cells[COLS.actions];
      td.className = "quick-delete";
      var edit = document.createElement("a");
      edit.href = child.url;
      edit.className = "quick-edit";
      edit.title = "Modifier";
      edit.setAttribute("aria-label", "Modifier " + child.name);
      edit.innerHTML = PENCIL;
      td.appendChild(edit);
      if (canDelete) {
        var del = document.createElement("a");
        del.href = child.url.replace("/change/", "/delete/");
        del.className = "quick-trash";
        del.title = "Supprimer";
        del.setAttribute("aria-label", "Supprimer " + child.name);
        del.innerHTML = TRASH;
        td.appendChild(del);
      }
    }
    return tr;
  }

  table.addEventListener("click", function (event) {
    var btn = event.target.closest(".org-toggle");
    if (!btn) return;
    event.preventDefault();
    var row = btn.closest("tr");
    var open = btn.getAttribute("aria-expanded") === "true";
    var count = btn.textContent.replace(/[^0-9]/g, "");
    if (open) {
      while (row.nextElementSibling && row.nextElementSibling.classList.contains("org-child-row")) {
        row.nextElementSibling.remove();
      }
    } else {
      var children = [];
      try { children = JSON.parse(btn.getAttribute("data-children") || "[]"); } catch (e) { children = []; }
      var anchor = row;
      children.forEach(function (child) {
        var tr = childRow(child);
        anchor.after(tr);
        anchor = tr;
      });
    }
    btn.setAttribute("aria-expanded", open ? "false" : "true");
    btn.textContent = (open ? "▸ " : "▾ ") + count;
    row.classList.toggle("org-expanded", !open);
  });
});
