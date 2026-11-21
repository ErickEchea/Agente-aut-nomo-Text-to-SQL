// Applies the saved theme before first paint (an external file: the CSP forbids inline scripts).
(function () {
  var theme = "dark";
  try {
    var saved = window.localStorage.getItem("nexus.theme");
    if (saved === "light") theme = "light";
    else if (saved === "system" && window.matchMedia("(prefers-color-scheme: light)").matches) theme = "light";
    var locale = window.localStorage.getItem("nexus.locale");
    if (locale === "en") document.documentElement.lang = "en";
  } catch (e) {
    // Storage unavailable: keep the dark default.
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
