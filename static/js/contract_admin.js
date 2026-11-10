/* Admin contrat : filtrage dynamique des clients finaux (selon l'ESN)
   et des critères selon la formule choisie. */
/* L'admin charge ce script dans <head> : on attend que le formulaire existe. */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";

  function parseMap(el, attr) {
    var raw = el && el.getAttribute(attr);
    if (!raw) return {};
    try { return JSON.parse(raw); } catch (e) { return {}; }
  }

  function byId(id) { return document.getElementById(id); }

  function rowOf(el) { return el && (el.closest(".form-row") || el.parentElement); }

  // --- Client final : liste déroulante des clients finaux de l'ESN choisie ---
  // Les options sont reconstruites (et non simplement masquées) : une option
  // cachée reste sélectionnable au clavier sur certains navigateurs.
  var clientSel = byId("id_client");
  var endClientsSel = byId("id_end_clients");
  if (clientSel && endClientsSel) {
    var esnMap = parseMap(clientSel, "data-end-clients");
    var multiple = endClientsSel.multiple;
    var allOptions = Array.prototype.filter.call(endClientsSel.options, function (o) { return o.value; })
      .map(function (o) { return { value: o.value, text: o.text, selected: o.selected }; });
    var initialClient = clientSel.value;
    function filterEndClients() {
      var allowed = clientSel.value ? (esnMap[clientSel.value] || []) : [];
      var keep = {};
      Array.prototype.forEach.call(endClientsSel.options, function (o) { if (o.value) keep[o.value] = o.selected; });
      endClientsSel.innerHTML = "";
      var placeholder = multiple ? null : new Option("", "");
      if (placeholder) endClientsSel.appendChild(placeholder);
      var shown = 0, picked = false;
      allOptions.forEach(function (o) {
        // Un client final déjà couvert reste affiché tant que l'ESN n'a pas changé.
        var historical = o.selected && clientSel.value === initialClient;
        if (allowed.indexOf(parseInt(o.value, 10)) === -1 && !historical) return;
        var opt = new Option(o.text, o.value);
        opt.selected = o.value in keep ? keep[o.value] : historical;
        picked = picked || opt.selected;
        endClientsSel.appendChild(opt);
        shown++;
      });
      if (placeholder) {
        placeholder.text = !clientSel.value ? "— Choisissez d'abord l'ESN —"
          : (shown ? "— Sélectionnez le client final —" : "— Aucun client final pour cette ESN —");
        placeholder.selected = !picked;
        endClientsSel.disabled = !clientSel.value || !shown;
      }
    }
    // Un champ désactivé n'est pas envoyé : on le réactive juste avant l'envoi.
    var form = endClientsSel.form;
    if (form) form.addEventListener("submit", function () { endClientsSel.disabled = false; });
    clientSel.addEventListener("change", filterEndClients);
    filterEndClients();
  }

  // --- Forfait de tickets : repris de la formule choisie ---
  // Le champ reste modifiable : une valeur saisie à la main n'est jamais écrasée
  // (on ne remplace que si le champ est vide ou contient la dernière valeur proposée).
  var formulaSel = byId("id_contract_type");
  var allowance = byId("id_allowance_tickets");
  if (formulaSel && allowance) {
    var allowances = parseMap(formulaSel, "data-allowances");
    var proposed = null;
    formulaSel.addEventListener("change", function () {
      if (!(formulaSel.value in allowances)) return;
      var value = allowances[formulaSel.value];
      var text = value === null ? "" : String(value);
      if (allowance.value === "" || allowance.value === proposed) {
        allowance.value = text;
        proposed = text;
      }
    });
    // Nouveau contrat déjà positionné sur une formule (ex. retour d'erreur) : on ne
    // touche pas à la saisie, mais on considère la valeur actuelle comme proposée
    // si elle correspond à la formule.
    if (formulaSel.value in allowances) {
      var current = allowances[formulaSel.value];
      if (allowance.value === (current === null ? "" : String(current))) proposed = allowance.value;
    }
  }

  // --- Critères : inclus (grisés, non cochables) / suppléments (cochables) ---
  var typeSel = byId("id_contract_type");
  var extraBox = byId("id_extra_features");
  var excludedBox = byId("id_excluded_features");
  if (!typeSel || !extraBox) return;

  var typeMap = parseMap(typeSel, "data-features");
  var hint = document.createElement("p");
  hint.className = "fc-hint";
  hint.textContent = "Choisissez d'abord une formule.";
  rowOf(extraBox).parentNode.insertBefore(hint, rowOf(extraBox));

  function boxes(container) {
    return container ? container.querySelectorAll('input[type="checkbox"]') : [];
  }

  function refreshSummaries() {
    document.dispatchEvent(new CustomEvent("fc:refresh"));
  }

  function applyFormula() {
    var chosen = !!typeSel.value;
    var included = typeMap[typeSel.value] || [];
    hint.hidden = chosen;
    rowOf(extraBox).hidden = !chosen;
    if (excludedBox) rowOf(excludedBox).hidden = !chosen;
    if (!chosen) return;

    boxes(extraBox).forEach(function (box) {
      var inc = included.indexOf(parseInt(box.value, 10)) !== -1;
      var label = box.closest(".fc-row");
      if (inc) {
        box.checked = true;
      } else if (box.dataset.included === "1") {
        box.checked = false; // était inclus dans l'ancienne formule : ce n'est pas un supplément
      }
      box.disabled = inc;
      box.dataset.included = inc ? "1" : "";
      if (label) label.classList.toggle("is-included", inc);
    });

    // Critères retirés : seuls ceux de la formule peuvent l'être.
    boxes(excludedBox).forEach(function (box) {
      var inc = included.indexOf(parseInt(box.value, 10)) !== -1;
      var label = box.closest(".fc-row");
      if (label) label.hidden = !inc;
      if (!inc) box.checked = false;
    });
    refreshSummaries();
  }

  typeSel.addEventListener("change", applyFormula);
  applyFormula();
});

/* Solutions : carte d'import Excel placée sous le titre de la section. Le fichier
   choisi (ou déposé) est lu par le serveur sans rien enregistrer ; ses lignes
   remplissent le tableau des solutions, à vérifier avant d'enregistrer le contrat.
   Une solution de même nom déjà dans le tableau est mise à jour au lieu d'être dupliquée. */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";
  var card = document.querySelector("[data-sol-import]");
  if (!card) return;
  var group = document.getElementById("solutions-group");
  var heading = group && group.querySelector("fieldset > h2, h2");
  if (heading) heading.parentNode.insertBefore(card, heading.nextSibling);

  var input = card.querySelector('input[type="file"]');
  var result = card.querySelector("[data-sol-result]");
  var readUrl = card.getAttribute("data-read-url");
  if (!input || !group || !readUrl || !window.fetch) return;  // repli : import à l'enregistrement
  var prefix = "solutions";

  function csrf() {
    var el = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return el ? el.value : "";
  }

  function show(kind, html) {
    result.className = "sol-import__result is-" + kind;
    result.innerHTML = html;
    result.hidden = false;
  }

  function esc(text) {
    var d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML;
  }

  function field(index, name) {
    return document.getElementById("id_" + prefix + "-" + index + "-" + name);
  }

  function totalForms() {
    return parseInt(document.getElementById("id_" + prefix + "-TOTAL_FORMS").value, 10) || 0;
  }

  function findByName(name) {
    var key = name.trim().toLowerCase();
    for (var i = 0; i < totalForms(); i++) {
      var input = field(i, "name");
      var del = field(i, "DELETE");
      if (input && input.value.trim().toLowerCase() === key && !(del && del.checked)) return i;
    }
    return -1;
  }

  function emptyRow() {
    // Ligne vide déjà présente (ajoutée à la main mais pas remplie) : on la réutilise.
    for (var i = 0; i < totalForms(); i++) {
      var name = field(i, "name");
      var pk = field(i, "id");
      if (name && !name.value && !(pk && pk.value)) {
        var row = name.closest("tr");
        if (row && !row.classList.contains("empty-form")) return i;
      }
    }
    return -1;
  }

  function addRow() {
    var link = group.querySelector(".add-row a");
    if (!link) return -1;
    link.click();
    return totalForms() - 1;
  }

  function fill(index, data) {
    Object.keys(data).forEach(function (key) {
      var el = field(index, key);
      if (!el || key === "line") return;
      if (el.type === "checkbox") el.checked = !!data[key];
      else el.value = data[key] == null ? "" : data[key];
      el.dispatchEvent(new Event("change", { bubbles: true }));
    });
    var row = field(index, "name").closest("tr");
    if (row) {
      row.classList.add("sol-row-imported");
      setTimeout(function () { row.classList.remove("sol-row-imported"); }, 2500);
    }
  }

  function load(file) {
    if (!file) return;
    show("loading", esc("Lecture de « " + file.name + " »…"));
    var body = new FormData();
    body.append("file", file);
    fetch(readUrl, {
      method: "POST", body: body, credentials: "same-origin",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" },
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, errors: ["Réponse inattendue du serveur."] }; });
    }).then(function (data) {
      // Le fichier a été versé dans le tableau : il ne doit pas être réimporté à l'enregistrement.
      input.value = "";
      var errors = (data.errors || []).map(function (e) { return "<li>" + esc(e) + "</li>"; }).join("");
      if (!data.ok) {
        show("error", "<strong>Fichier non importé.</strong>" + (errors ? "<ul>" + errors + "</ul>" : ""));
        return;
      }
      var added = 0, updated = 0;
      data.rows.forEach(function (row) {
        var index = findByName(row.name);
        if (index >= 0) { updated++; }
        else {
          index = emptyRow();
          if (index < 0) index = addRow();
          if (index < 0) return;
          added++;
        }
        fill(index, row);
      });
      var parts = [];
      if (added) parts.push(added + (added > 1 ? " solutions ajoutées" : " solution ajoutée"));
      if (updated) parts.push(updated + (updated > 1 ? " solutions mises à jour" : " solution mise à jour"));
      var summary = parts.length ? parts.join(", ") : "Aucune solution trouvée dans le fichier";
      show(errors ? "warning" : "success",
        "<strong>" + esc(file.name) + "</strong> : " + summary + ". Vérifiez le tableau, puis enregistrez le contrat."
        + (errors ? "<ul>" + errors + "</ul>" : ""));
    }).catch(function () {
      input.value = "";
      show("error", "<strong>Lecture impossible.</strong> Vérifiez votre connexion et réessayez.");
    });
  }

  input.addEventListener("change", function () { load(input.files && input.files[0]); });

  ["dragenter", "dragover"].forEach(function (type) {
    card.addEventListener(type, function (e) { e.preventDefault(); card.classList.add("is-dragover"); });
  });
  ["dragleave", "drop"].forEach(function (type) {
    card.addEventListener(type, function (e) {
      e.preventDefault();
      if (type === "dragleave" && card.contains(e.relatedTarget)) return;
      card.classList.remove("is-dragover");
    });
  });
  card.addEventListener("drop", function (e) {
    var files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length) load(files[0]);
  });
});
