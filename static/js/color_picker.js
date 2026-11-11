/* Fiche organisation : sélecteur de « Couleur de l'entreprise » intégré à la page.
   Le sélecteur natif du navigateur s'ouvre où il veut (souvent vers le haut, sur le formulaire) ;
   celui-ci s'ouvre toujours sous le champ, un peu à droite. Le champ d'origine (input type=color,
   valeur #RRVVBB) reste celui qui est envoyé avec le formulaire. */
(function (init) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(function () {
  "use strict";

  var input = document.getElementById("id_brand_color");
  if (!input) return;

  // --- Conversions --------------------------------------------------------------------
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  function hexToRgb(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return null;
    var n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function rgbToHex(r, g, b) {
    return "#" + [r, g, b].map(function (v) { return clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0"); })
      .join("").toUpperCase();
  }
  function rgbToHsv(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    var max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min, h = 0;
    if (d) {
      if (max === r) h = ((g - b) / d) % 6;
      else if (max === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      h *= 60;
      if (h < 0) h += 360;
    }
    return [h, max ? d / max : 0, max];
  }
  function hsvToRgb(h, s, v) {
    var c = v * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = v - c, rgb;
    if (h < 60) rgb = [c, x, 0]; else if (h < 120) rgb = [x, c, 0]; else if (h < 180) rgb = [0, c, x];
    else if (h < 240) rgb = [0, x, c]; else if (h < 300) rgb = [x, 0, c]; else rgb = [c, 0, x];
    return rgb.map(function (t) { return (t + m) * 255; });
  }

  // --- Construction ------------------------------------------------------------------
  var wrap = document.createElement("span");
  wrap.className = "cp-wrap";
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  input.setAttribute("aria-haspopup", "dialog");
  input.setAttribute("aria-expanded", "false");

  var panel = document.createElement("div");
  panel.className = "cp-panel";
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Choisir la couleur de l'entreprise");
  panel.innerHTML =
    '<div class="cp-sv" tabindex="0" aria-label="Saturation et luminosité"><div class="cp-sv-dot"></div></div>'
    + '<div class="cp-row">'
    + (window.EyeDropper ? '<button type="button" class="cp-eye" title="Prendre une couleur à l\'écran" aria-label="Pipette">'
      + '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
      + 'stroke-linejoin="round" aria-hidden="true"><path d="m2 22 1-1h3l9-9"/><path d="M3 21v-3l9-9"/>'
      + '<path d="m15 6 3.4-3.4a2.1 2.1 0 1 1 3 3L18 9l.4.4a2.1 2.1 0 1 1-3 3l-3.8-3.8a2.1 2.1 0 1 1 3-3l.4.4Z"/></svg></button>' : "")
    + '<span class="cp-preview" aria-hidden="true"></span>'
    + '<div class="cp-hue" tabindex="0" aria-label="Teinte"><div class="cp-hue-dot"></div></div></div>'
    + '<div class="cp-fields">'
    + '<label><input class="cp-hex" type="text" maxlength="7" spellcheck="false" aria-label="Code hexadécimal"><span>Hex</span></label>'
    + '<label><input class="cp-r" type="number" min="0" max="255" aria-label="Rouge"><span>R</span></label>'
    + '<label><input class="cp-g" type="number" min="0" max="255" aria-label="Vert"><span>V</span></label>'
    + '<label><input class="cp-b" type="number" min="0" max="255" aria-label="Bleu"><span>B</span></label>'
    + '</div>';
  wrap.appendChild(panel);

  var sv = panel.querySelector(".cp-sv"), svDot = panel.querySelector(".cp-sv-dot");
  var hue = panel.querySelector(".cp-hue"), hueDot = panel.querySelector(".cp-hue-dot");
  var preview = panel.querySelector(".cp-preview"), hexField = panel.querySelector(".cp-hex");
  var rgbFields = [panel.querySelector(".cp-r"), panel.querySelector(".cp-g"), panel.querySelector(".cp-b")];

  var state = [0, 0, 0];  // h, s, v

  function render(skip) {
    var rgb = hsvToRgb(state[0], state[1], state[2]), hex = rgbToHex(rgb[0], rgb[1], rgb[2]);
    sv.style.backgroundColor = "hsl(" + state[0] + ", 100%, 50%)";
    svDot.style.left = (state[1] * 100) + "%";
    svDot.style.top = ((1 - state[2]) * 100) + "%";
    hueDot.style.left = (state[0] / 360 * 100) + "%";
    preview.style.background = hex;
    if (skip !== "hex") hexField.value = hex;
    if (skip !== "rgb") rgbFields.forEach(function (f, i) { f.value = Math.round(rgb[i]); });
    if (input.value.toUpperCase() !== hex) {
      input.value = hex;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
  function setHex(hex, skip) {
    var rgb = hexToRgb(hex);
    if (!rgb) return;
    var hsv = rgbToHsv(rgb[0], rgb[1], rgb[2]);
    if (!hsv[1] || !hsv[2]) hsv[0] = state[0];  // gris : garder la teinte en cours
    state = hsv;
    render(skip);
  }

  function drag(el, onMove) {
    el.addEventListener("pointerdown", function (e) {
      e.preventDefault();
      el.focus();
      el.setPointerCapture(e.pointerId);
      var move = function (ev) {
        var r = el.getBoundingClientRect();
        onMove(clamp((ev.clientX - r.left) / r.width, 0, 1), clamp((ev.clientY - r.top) / r.height, 0, 1));
      };
      move(e);
      el.onpointermove = move;
      el.onpointerup = function () { el.onpointermove = el.onpointerup = null; };
    });
  }
  drag(sv, function (x, y) { state[1] = x; state[2] = 1 - y; render(); });
  drag(hue, function (x) { state[0] = Math.min(359.9, x * 360); render(); });

  sv.addEventListener("keydown", function (e) {
    var step = e.shiftKey ? 0.1 : 0.02, keys = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
    if (!keys[e.key]) return;
    e.preventDefault();
    state[1] = clamp(state[1] + keys[e.key][0], 0, 1);
    state[2] = clamp(state[2] + keys[e.key][1], 0, 1);
    render();
  });
  hue.addEventListener("keydown", function (e) {
    var d = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1 }[e.key];
    if (!d) return;
    e.preventDefault();
    state[0] = clamp(state[0] + d * (e.shiftKey ? 15 : 3), 0, 359.9);
    render();
  });
  hexField.addEventListener("input", function () {
    var v = hexField.value.trim();
    if (v && v[0] !== "#") v = "#" + v;
    if (/^#[0-9a-f]{6}$/i.test(v)) setHex(v, "hex");
  });
  hexField.addEventListener("blur", function () { render(); });
  rgbFields.forEach(function (f) {
    f.addEventListener("input", function () {
      var c = rgbFields.map(function (x) { return clamp(parseInt(x.value, 10) || 0, 0, 255); });
      setHex(rgbToHex(c[0], c[1], c[2]), "rgb");
    });
  });
  var eye = panel.querySelector(".cp-eye");
  if (eye) eye.addEventListener("click", function () {
    new window.EyeDropper().open().then(function (res) { setHex(res.sRGBHex); }).catch(function () {});
  });

  // --- Ouverture / fermeture ------------------------------------------------------------
  function open() {
    setHex(input.value || "#3B4652");
    panel.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }
  function close(refocus) {
    if (panel.hidden) return;
    panel.hidden = true;
    input.setAttribute("aria-expanded", "false");
    if (refocus) input.focus();
  }
  // Le clic sur le champ couleur n'ouvre plus le sélecteur du navigateur.
  input.addEventListener("click", function (e) {
    e.preventDefault();
    if (panel.hidden) open(); else close();
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (panel.hidden) open(); else close(); }
  });
  document.addEventListener("pointerdown", function (e) { if (!wrap.contains(e.target)) close(false); });
  panel.addEventListener("keydown", function (e) { if (e.key === "Escape") { e.preventDefault(); close(true); } });
});
