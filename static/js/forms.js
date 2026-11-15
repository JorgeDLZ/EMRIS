(function () {
  var MAX_SUGGESTIONS = 10;

  function normalize(text) {
    return text
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .toUpperCase();
  }

  function readOptions() {
    var data = document.getElementById("municipality-options");
    if (!data) {
      return [];
    }
    return JSON.parse(data.textContent).map(function (row) {
      return { id: String(row[0]), name: row[1], departmentId: String(row[2]), departmentCode: row[3], key: normalize(row[1]) };
    });
  }

  function enhance(field, options, index) {
    var departmentField = document.getElementById(field.getAttribute("data-department-field"));
    var byCode = field.getAttribute("data-department-key") === "code";
    var textMode = field.getAttribute("data-combobox-mode") === "text";
    var input = textMode ? field : document.createElement("input");
    var list = document.createElement("ul");
    var listId = "combobox-list-" + index;
    var matches = [];
    var active = -1;

    list.id = listId;
    list.className = "combobox-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;

    if (!textMode) {
      input.type = "text";
      input.id = field.id + "_search";
      input.className = "combobox-input";
      var label = document.querySelector('label[for="' + field.id + '"]');
      if (label) {
        label.setAttribute("for", input.id);
      }
      var selected = field.options[field.selectedIndex];
      input.value = selected && selected.value ? selected.text.replace(/\s*\(.*\)$/, "") : "";
      input.required = field.required;
      field.required = false;
      ["aria-invalid", "aria-describedby"].forEach(function (name) {
        if (field.hasAttribute(name)) {
          input.setAttribute(name, field.getAttribute(name));
        }
      });
      field.hidden = true;
      field.setAttribute("tabindex", "-1");
      field.parentNode.insertBefore(input, field.nextSibling);
    }
    input.setAttribute("role", "combobox");
    input.setAttribute("autocomplete", "off");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", listId);
    input.parentNode.insertBefore(list, input.nextSibling);

    function departmentValue() {
      return departmentField ? departmentField.value : "";
    }

    function inDepartment(option) {
      var department = departmentValue();
      if (!department) {
        return true;
      }
      return (byCode ? option.departmentCode : option.departmentId) === department;
    }

    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      active = -1;
    }

    function setActive(position) {
      var items = list.children;
      if (active >= 0 && items[active]) {
        items[active].removeAttribute("aria-selected");
      }
      active = position;
      if (active >= 0 && items[active]) {
        items[active].setAttribute("aria-selected", "true");
        input.setAttribute("aria-activedescendant", items[active].id);
      }
    }

    function choose(option) {
      input.value = option.name;
      if (!textMode) {
        field.value = option.id;
      }
      if (departmentField && !departmentValue()) {
        departmentField.value = byCode ? option.departmentCode : option.departmentId;
      }
      close();
    }

    function render() {
      var query = normalize(input.value);
      matches = options.filter(function (option) {
        return inDepartment(option) && (!query || option.key.indexOf(query) !== -1);
      }).slice(0, MAX_SUGGESTIONS);
      list.textContent = "";
      matches.forEach(function (option, position) {
        var item = document.createElement("li");
        item.id = listId + "-" + position;
        item.className = "combobox-option";
        item.setAttribute("role", "option");
        item.textContent = option.name;
        item.addEventListener("mousedown", function (event) {
          event.preventDefault();
          choose(option);
        });
        list.appendChild(item);
      });
      list.hidden = matches.length === 0;
      input.setAttribute("aria-expanded", String(matches.length > 0));
      active = -1;
      input.removeAttribute("aria-activedescendant");
    }

    input.addEventListener("input", function () {
      if (!textMode) {
        field.value = "";
      }
      render();
    });
    input.addEventListener("focus", render);
    input.addEventListener("blur", close);
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (list.hidden) {
          render();
        }
        if (matches.length) {
          var step = event.key === "ArrowDown" ? 1 : -1;
          setActive((active + step + matches.length) % matches.length);
        }
      } else if (event.key === "Enter" && !list.hidden && active >= 0) {
        event.preventDefault();
        choose(matches[active]);
      } else if (event.key === "Escape" && !list.hidden) {
        event.preventDefault();
        close();
      }
    });

    if (departmentField) {
      departmentField.addEventListener("change", function () {
        var current = options.filter(function (option) {
          return textMode ? option.key === normalize(input.value) : option.id === field.value;
        })[0];
        if (current && !inDepartment(current)) {
          input.value = "";
          if (!textMode) {
            field.value = "";
          }
        }
      });
    }
  }

  function bindEarthquakeSection(section) {
    var type = document.getElementById("id_emergency_type");
    if (!type) {
      return;
    }
    function update() {
      var selected = type.options[type.selectedIndex];
      var isEarthquake = Boolean(selected && selected.getAttribute("data-earthquake") === "true");
      section.hidden = !isEarthquake;
      if (!isEarthquake) {
        Array.prototype.forEach.call(section.querySelectorAll("input"), function (input) {
          input.value = "";
        });
      }
    }
    type.addEventListener("change", update);
    update();
  }

  document.addEventListener("DOMContentLoaded", function () {
    var section = document.querySelector('[data-show-when="earthquake"]');
    if (section) {
      bindEarthquakeSection(section);
    }
    var fields = document.querySelectorAll('[data-combobox="municipality"]');
    if (!fields.length) {
      return;
    }
    var options = readOptions();
    Array.prototype.forEach.call(fields, function (field, index) {
      enhance(field, options, index);
    });
  });

  document.addEventListener("DOMContentLoaded", function () {
    var summary = document.querySelector(".error-summary");
    if (!summary) {
      return;
    }
    Array.prototype.forEach.call(summary.querySelectorAll('a[href^="#"]'), function (link) {
      var search = document.getElementById(link.getAttribute("href").slice(1) + "_search");
      if (search) {
        link.setAttribute("href", "#" + search.id);
      }
    });
    summary.focus();
  });
})();
