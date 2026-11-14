(function () {
  document.documentElement.classList.add("js");

  function setOpen(toggle, sidebar, open) {
    toggle.setAttribute("aria-expanded", String(open));
    sidebar.classList.toggle("is-open", open);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.querySelector(".menu-toggle");
    var sidebar = document.getElementById(toggle ? toggle.getAttribute("aria-controls") : "");
    if (!toggle || !sidebar) {
      return;
    }
    toggle.addEventListener("click", function () {
      setOpen(toggle, sidebar, toggle.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(toggle, sidebar, false);
        toggle.focus();
      }
    });
  });
})();
