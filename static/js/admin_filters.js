// Filtres de l'administration : choisir une valeur applique le filtre (sans bouton « Valider »).
(function () {
  document.querySelectorAll("select[data-admin-filter]").forEach(function (select) {
    select.addEventListener("change", function () {
      if (select.value) window.location.href = select.value;
    });
  });
})();
