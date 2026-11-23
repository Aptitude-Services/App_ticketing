// Fiche utilisateur de l'administration : la liste « Profil » ne propose que les profils
// compatibles avec l'organisation choisie (profils internes pour Aptitude, profils clients
// pour les autres). Le contrôle de fond reste User.clean côté serveur.
(function () {
  function init() {
    var profile = document.getElementById("id_profile");
    var org = document.getElementById("id_organisation");
    if (!profile || !org || profile.dataset.aptitudeProfiles === undefined) return;

    var internal = profile.dataset.aptitudeProfiles.split(",");
    var operator = profile.dataset.operatorOrg;
    var options = Array.prototype.map.call(profile.options, function (o) {
      return { value: o.value, label: o.textContent };
    });
    var initial = profile.value;

    function sync(first) {
      var current = profile.value;
      var isAptitude = org.value !== "" && org.value === operator;
      profile.replaceChildren();
      options.forEach(function (o) {
        var fits = o.value === "" || !org.value || (internal.indexOf(o.value) !== -1) === isAptitude;
        // Au chargement, on garde le profil déjà porté par le compte, même incohérent,
        // pour ne pas le changer à l'insu de l'utilisateur.
        if (fits || (first && o.value === initial)) {
          profile.appendChild(new Option(o.label, o.value));
        }
      });
      var still = Array.prototype.some.call(profile.options, function (o) { return o.value === current; });
      profile.value = still ? current : "";
    }

    org.addEventListener("change", function () { sync(false); });
    sync(true);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
