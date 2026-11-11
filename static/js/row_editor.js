/* Saisie en tableau (ex. chronologie : Date | Heure | Action).
   La zone de texte d'origine (une ligne par entrée, colonnes séparées par « | ») reste
   le champ envoyé au serveur : elle est masquée et tenue à jour à chaque saisie.
   Colonnes : data-row-editor='[{"label": "Date", "type": "date"}, …]' (date, time, text, ou
   select avec "options": […]). */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";

  var TRASH = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
    + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/>'
    + '<path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>';

  function toIsoDate(value) {
    var m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(value || "");
    if (m) return m[3] + "-" + ("0" + m[2]).slice(-2) + "-" + ("0" + m[1]).slice(-2);
    return value || "";
  }

  document.querySelectorAll("textarea[data-row-editor]").forEach(function (area) {
    var cols;
    try { cols = JSON.parse(area.getAttribute("data-row-editor")); } catch (e) { return; }
    var last = cols.length - 1;

    var wrap = document.createElement("div");
    wrap.className = "row-editor";
    var table = document.createElement("table");
    table.innerHTML = "<thead><tr>" + cols.map(function (c) {
      return '<th class="re-' + c.type + '">' + c.label + "</th>";
    }).join("") + '<th class="re-del"><span class="sr-only">Supprimer</span></th></tr></thead><tbody></tbody>';
    var body = table.querySelector("tbody");
    var add = document.createElement("button");
    add.type = "button";
    add.className = "btn btn-secondary re-add";
    add.textContent = "+ " + (area.getAttribute("data-add-label") || "Ajouter une ligne");
    wrap.appendChild(table);
    wrap.appendChild(add);
    area.hidden = true;
    area.parentNode.insertBefore(wrap, area);

    function sync() {
      var lines = [];
      body.querySelectorAll("tr").forEach(function (tr) {
        // « | » sépare les colonnes : on le remplace s'il est tapé dans un champ.
        var cells = Array.prototype.map.call(tr.querySelectorAll("[data-col]"), function (i) {
          return i.value.replace(/[\r\n]+/g, " ").replace(/\|/g, "/").trim();
        });
        if (cells.some(function (v) { return v; })) lines.push(cells.join(" | "));
      });
      area.value = lines.join("\n");
    }

    function addRow(values, focus) {
      var tr = document.createElement("tr");
      cols.forEach(function (c, i) {
        var td = document.createElement("td");
        var v = (values[i] || "").trim();
        if (c.type === "date") v = toIsoDate(v);
        if (i === last && values.length > cols.length) v = values.slice(last).join(" | ").trim();
        var input;
        if (c.type === "select") {
          input = document.createElement("select");
          var opts = [""].concat(c.options || []);
          // Valeur saisie avant la liste : conservée telle quelle.
          if (v && opts.indexOf(v) === -1) opts.push(v);
          opts.forEach(function (o) { input.appendChild(new Option(o || "—", o)); });
        } else {
          input = document.createElement("input");
          input.type = c.type === "date" ? "date" : c.type === "time" ? "time" : "text";
        }
        input.setAttribute("data-col", i);
        input.setAttribute("aria-label", c.label);
        input.value = v;
        if (c.type === "text") input.placeholder = c.label;
        input.addEventListener("input", sync);
        input.addEventListener("change", sync);
        td.appendChild(input);
        tr.appendChild(td);
      });
      var del = document.createElement("td");
      del.className = "re-del";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "re-remove";
      btn.title = "Supprimer cette ligne";
      btn.setAttribute("aria-label", "Supprimer cette ligne");
      btn.innerHTML = TRASH;
      btn.addEventListener("click", function () {
        tr.remove();
        if (!body.children.length) addRow([], false);
        sync();
      });
      del.appendChild(btn);
      tr.appendChild(del);
      body.appendChild(tr);
      if (focus) (tr.querySelector('input[type="text"]') || tr.querySelector("[data-col]")).focus();
      return tr;
    }

    var lines = area.value.split(/\r?\n/).filter(function (l) { return l.trim(); });
    lines.forEach(function (line) { addRow(line.split("|"), false); });
    if (!lines.length) addRow([], false);

    add.addEventListener("click", function () {
      // La nouvelle étape reprend la date de la précédente : souvent le même jour.
      var rows = body.querySelectorAll("tr");
      var prev = rows.length ? rows[rows.length - 1].querySelectorAll("[data-col]") : [];
      var seed = cols.map(function (c, i) { return c.type === "date" && prev[i] ? prev[i].value : ""; });
      addRow(seed, true);
      sync();
    });
    sync();
  });
});
