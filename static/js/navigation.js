(function () {
  var toggle = document.querySelector(".menu-toggle");
  var sidebar = document.getElementById(toggle ? toggle.getAttribute("aria-controls") : "");
  document.documentElement.classList.add("js");
  if (!toggle || !sidebar) {
    return;
  }
  toggle.addEventListener("click", function () {
    var open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open));
    sidebar.classList.toggle("is-open", open);
  });
})();
