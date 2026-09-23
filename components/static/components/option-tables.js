/*
 * Сетка таблиц в конструкторе выпадающих списков (админка).
 *
 * Кнопки «все рабочие / все замены / снять все» и отметка пары щелчком по
 * названию группы: почти каждый список заводят парой «таблица + её замены».
 * Разметка — components/widgets/option_tables.html. Кнопки там скрыты и
 * показываются только отсюда: без скрипта они бы ничего не делали.
 *
 * Скрипт админки, а не сайта: HTMX в админке нет, поэтому хватает
 * DOMContentLoaded — регистрироваться в window.OY незачем.
 */
(function () {
  "use strict";

  function boxes(scope) {
    return Array.prototype.slice.call(
      scope.querySelectorAll('input[type="checkbox"]'));
  }

  function setup(root) {
    var tools = root.querySelector(".oy-tables__tools");
    if (tools) {
      tools.hidden = false;
    }

    root.addEventListener("click", function (event) {
      var tool = event.target.closest("[data-pick]");
      if (tool) {
        var kind = tool.getAttribute("data-pick");
        boxes(root).forEach(function (box) {
          if (kind === "none") {
            box.checked = false;
          } else if (box.getAttribute("data-kind") === kind) {
            box.checked = true;
          }
        });
        return;
      }

      var group = event.target.closest("[data-pair]");
      if (group) {
        // обе отмечены — снимаем обе; иначе отмечаем обе
        var pair = boxes(group.closest("tr"));
        var all = pair.every(function (box) { return box.checked; });
        pair.forEach(function (box) { box.checked = !all; });
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-oy-tables]"), setup);
  });
})();
