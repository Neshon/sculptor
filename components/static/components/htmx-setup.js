/* HTMX на страницах справочника: то, что нужно каждому куску страницы.
 *
 * Подключается после htmx.min.js и только вместе с ним (base.html). Если
 * файла htmx нет, этот скрипт не подключается вовсе, и сайт работает
 * обычными переходами.
 *
 * 1. Скрипты страницы — вкладки, выпадающие списки, даты, поля файлов — один раз
 *    при загрузке находят свои элементы и оформляют их. Кусок, который
 *    HTMX вставил позже, остался бы голым. htmx.onLoad вызывается для
 *    каждого вставленного куска (и для страницы при загрузке); повторную
 *    обработку уже оформленных элементов скрипты отсекают сами.
 *
 * 2. Ответы с ошибкой HTMX на страницу не выводит: кнопка просто «ничего
 *    не делает». Показываем уведомление тем же видом, что и сообщения
 *    Django, — в углу, и оно уходит само.
 */
(function () {
  if (!window.htmx) { return; }

  // Перед заменой куска: открытое меню выпадающего списка и календарь
  // лежат в body и остались бы висеть без своего поля (select.js,
  // date.js — beforeSwap)
  document.body.addEventListener("htmx:beforeSwap", function (event) {
    var oy = window.OY || {};
    ["selectsBeforeSwap", "datesBeforeSwap"].forEach(function (name) {
      if (typeof oy[name] === "function") { oy[name](event.detail.target); }
    });
  });

  htmx.onLoad(function (root) {
    var oy = window.OY || {};
    ["tabs", "selects", "dates", "files"].forEach(function (name) {
      if (typeof oy[name] === "function") { oy[name](root); }
    });
  });

  function toast(text) {
    var box = document.getElementById("toasts");
    if (!box) {
      box = document.createElement("div");
      box.id = "toasts";
      box.className = "notes";
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
      document.body.appendChild(box);
    }
    var note = document.createElement("div");
    note.className = "note note--error";
    note.textContent = text;
    box.appendChild(note);
    setTimeout(function () {
      note.classList.add("is-leaving");
      setTimeout(function () { note.remove(); }, 260);
    }, 6000);
  }

  document.body.addEventListener("htmx:responseError", function (event) {
    var status = event.detail.xhr ? event.detail.xhr.status : "";
    toast(status === 403
      ? "Недостаточно прав для этого действия."
      : "Не удалось обновить страницу (ошибка " + status + "). Обновите её целиком.");
  });

  document.body.addEventListener("htmx:sendError", function () {
    toast("Сервер не отвечает. Проверьте соединение и обновите страницу.");
  });
})();
