/* Saisie des contrôles réalisés (rapport préventif).
   Les contrôles sont regroupés par catégorie ; chaque ligne porte le contrôle, l'équipement
   (suggestions : équipements du rapport), le résultat en un clic et un commentaire.
   La zone de texte d'origine (Catégorie | Contrôle | Équipement | Résultat | Commentaire)
   reste le champ envoyé au serveur : elle est masquée et tenue à jour à chaque saisie.
   Configuration : data-controls-editor='{"results": [...], "equipments": [...]}'. */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";

  var TRASH = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
    + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/>'
    + '<path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>';
  var TONES = ["ok", "warn", "ko", "na"];
  var uid = 0;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function clean(v) { return (v || "").replace(/[\r\n|]+/g, " ").trim(); }

  document.querySelectorAll("textarea[data-controls-editor]").forEach(function (area) {
    var conf;
    try { conf = JSON.parse(area.getAttribute("data-controls-editor")); } catch (e) { return; }
    var results = conf.results || [];
    var listId = "ce-equipments-" + (++uid);

    var wrap = el("div", "controls-editor");
    var datalist = el("datalist");
    datalist.id = listId;
    (conf.equipments || []).forEach(function (name) {
      var o = document.createElement("option");
      o.value = name;
      datalist.appendChild(o);
    });
    var groups = el("div", "ce-groups");
    var addGroup = el("button", "btn btn-secondary ce-add-group", "+ Ajouter une catégorie");
    addGroup.type = "button";
    wrap.appendChild(datalist);
    wrap.appendChild(groups);
    wrap.appendChild(addGroup);
    area.hidden = true;
    area.parentNode.insertBefore(wrap, area);

    function sync() {
      var lines = [];
      groups.querySelectorAll(".ce-group").forEach(function (g) {
        var cat = clean(g.querySelector(".ce-cat").value);
        var rows = g.querySelectorAll(".ce-row"), done = 0;
        rows.forEach(function (row) {
          var result = row.getAttribute("data-result") || "";
          var cells = [cat, clean(row.querySelector(".ce-control").value), clean(row.querySelector(".ce-eq").value),
                       result, clean(row.querySelector(".ce-comment").value)];
          if (result) done++;
          if (cells.slice(1).some(function (v) { return v; })) {
            lines.push(cells.join(" | ").replace(/( \| )+$/, ""));
          }
        });
        g.querySelector(".ce-progress").textContent = done + " / " + rows.length;
      });
      area.value = lines.join("\n");
    }

    function setResult(row, value) {
      row.setAttribute("data-result", value);
      row.querySelectorAll(".ce-result button").forEach(function (b) {
        var on = b.getAttribute("data-value") === value;
        b.classList.toggle("is-on", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }

    function input(cls, placeholder, value) {
      var i = el("input", cls);
      i.type = "text";
      i.placeholder = placeholder;
      i.setAttribute("aria-label", placeholder);
      i.value = value || "";
      i.addEventListener("input", sync);
      return i;
    }

    function addRow(group, values, focus) {
      var row = el("div", "ce-row");
      var control = input("ce-control", "Contrôle", values[0]);
      var eq = input("ce-eq", "Équipement", values[1]);
      eq.setAttribute("list", listId);
      var res = el("div", "ce-result");
      res.setAttribute("role", "group");
      res.setAttribute("aria-label", "Résultat");
      results.forEach(function (r, i) {
        var b = el("button", "ce-" + (TONES[i] || "na"), r);
        b.type = "button";
        b.setAttribute("data-value", r);
        b.addEventListener("click", function () {
          // Un second clic sur le résultat choisi l'efface.
          setResult(row, row.getAttribute("data-result") === r ? "" : r);
          sync();
        });
        res.appendChild(b);
      });
      var comment = input("ce-comment", "Commentaire (annexe : A1…)", values[3]);
      var del = el("button", "ce-remove");
      del.type = "button";
      del.title = "Supprimer ce contrôle";
      del.setAttribute("aria-label", "Supprimer ce contrôle");
      del.innerHTML = TRASH;
      del.addEventListener("click", function () { row.remove(); sync(); });
      [control, eq, res, comment, del].forEach(function (n) { row.appendChild(n); });
      group.querySelector(".ce-rows").appendChild(row);
      var initial = (values[2] || "").trim();
      setResult(row, results.indexOf(initial) >= 0 ? initial : "");
      if (focus) control.focus();
      return row;
    }

    function addGroupEl(name, focus) {
      var g = el("section", "ce-group");
      var head = el("div", "ce-group-head");
      var cat = input("ce-cat", "Catégorie (ex. Sauvegardes)", name);
      var progress = el("span", "ce-progress");
      progress.title = "Contrôles dont le résultat est renseigné";
      var del = el("button", "ce-remove");
      del.type = "button";
      del.title = "Supprimer la catégorie et ses contrôles";
      del.setAttribute("aria-label", "Supprimer la catégorie et ses contrôles");
      del.innerHTML = TRASH;
      del.addEventListener("click", function () {
        var filled = Array.prototype.some.call(g.querySelectorAll(".ce-row input"), function (i) {
          return i.value.trim();
        });
        if (filled && !window.confirm("Supprimer cette catégorie et tous ses contrôles ?")) return;
        g.remove();
        sync();
      });
      [cat, progress, del].forEach(function (n) { head.appendChild(n); });
      var rows = el("div", "ce-rows");
      var add = el("button", "ce-add", "+ Ajouter un contrôle");
      add.type = "button";
      add.addEventListener("click", function () { addRow(g, [], true); sync(); });
      [head, rows, add].forEach(function (n) { g.appendChild(n); });
      groups.appendChild(g);
      if (focus) cat.focus();
      return g;
    }

    // Lecture du texte existant : un groupe par catégorie, dans l'ordre d'apparition.
    var byCat = {}, order = [];
    area.value.split(/\r?\n/).forEach(function (line) {
      if (!line.trim()) return;
      var c = line.split("|").map(function (x) { return x.trim(); });
      var cat = c[0] || "";
      if (!Object.prototype.hasOwnProperty.call(byCat, cat)) { byCat[cat] = []; order.push(cat); }
      byCat[cat].push([c[1], c[2], c[3], c.slice(4).join(" | ")]);
    });
    order.forEach(function (cat) {
      var g = addGroupEl(cat, false);
      byCat[cat].forEach(function (v) { addRow(g, v, false); });
    });
    if (!order.length) addRow(addGroupEl("", false), [], false);

    addGroup.addEventListener("click", function () {
      addRow(addGroupEl("", true), [], false);
      sync();
    });
    sync();
  });
});
