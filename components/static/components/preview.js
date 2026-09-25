/* Краткая карточка рядом со списком (#list-preview): компоненты
 * (components/list.html), платы (boards/list.html) и ревизии в карточке
 * платы (boards/detail.html).
 *
 * Панель закреплена справа от списка. При открытии списка в ней сразу
 * первая строка, щелчок по строке показывает другую, и список остаётся на
 * месте: можно пройти по строкам и сравнить, не уходя на карточку и
 * обратно. Содержимое отдаёт
 * вид карточки по тому же адресу, что у строки (detail.html#preview), —
 * поэтому без скрипта строка просто ведёт на карточку, как раньше.
 *
 * Подключается только вместе с htmx (base.html). Открытием строки
 * распоряжается общий обработчик щелчка в base.html: он зовёт
 * OY.openPreview, а если та отказалась — ведёт на карточку целиком.
 *
 * Стрелки вверх и вниз переключают соседние строки. Двойной щелчок по
 * строке — карточка целиком.
 */
(function () {
  var OY = window.OY = window.OY || {};

  function panel() { return document.getElementById("list-preview"); }

  // Хватает ли ширины на панель, решает CSS (--preview-on в app.css):
  // порог живёт в одном месте, рядом с раскладкой, которую он бережёт.
  // На узком окне панели нет — строка ведёт на карточку целиком
  function roomy(aside) {
    return getComputedStyle(aside.parentElement)
      .getPropertyValue("--preview-on").trim() === "1";
  }

  // Выбранная строка подсвечена: иначе, листая стрелками, не видно, чья
  // карточка сейчас справа
  function mark(url) {
    document.querySelectorAll("#list-rows tr[data-href]").forEach(function (row) {
      row.classList.toggle("is-previewed", !!url && row.dataset.href === url);
    });
  }

  // Показать строку в панели. true — панель взялась за строку, и переходить
  // по ссылке не нужно; false — места нет или htmx не загрузился
  OY.openPreview = function (row) {
    var aside = panel();
    if (!aside || !window.htmx || !roomy(aside)) { return false; }
    var url = row.dataset.href;
    mark(url);
    if (aside.dataset.url === url) { return true; }
    aside.dataset.url = url;
    // Заголовок HX-Target — id панели: по нему вид карточки отвечает
    // краткой версией (components/views.py, PREVIEW_TARGET). source —
    // сама панель, чтобы на ней сработал её hx-sync
    htmx.ajax("GET", url, { source: aside, target: aside, swap: "innerHTML" });
    return true;
  };

  // После замены списка (фильтр, страница, сортировка) строки новые, и
  // подсветку надо вернуть выбранной. Зовётся из htmx-setup.js для
  // каждого вставленного куска — и для самой панели тоже, поэтому берём
  // выбранную строку (url), а не ту, что была показана до ответа (shown).
  //
  // Пока не выбрано ничего, панель сама показывает первую строку: список
  // открыли — справа уже карточка, а не подсказка «выберите строку». Так
  // и при загрузке страницы (htmx.onLoad зовёт это для неё целиком), и
  // когда фильтр впервые дал строки после пустого списка. Выбранную
  // человеком строку это не трогает: после фильтра, где её больше нет,
  // панель остаётся на ней, а не прыгает на чужую первую
  OY.previews = function () {
    var aside = panel();
    if (!aside) { return; }
    if (aside.dataset.url) { mark(aside.dataset.url); return; }
    var first = document.querySelector("#list-rows tr[data-href]");
    if (first) { OY.openPreview(first); }
  };

  // что в панели сейчас на самом деле — к этому вернёмся, если следующая
  // строка не откроется
  document.addEventListener("htmx:afterSwap", function (event) {
    var aside = panel();
    if (aside && event.detail.target === aside) {
      aside.dataset.shown = aside.dataset.url;
    }
  });

  // Карточка не пришла (удалена, нет прав): об ошибке скажет htmx-setup.js,
  // а подсветка строки, которую так и не показали, сбила бы с толку
  document.addEventListener("htmx:responseError", function (event) {
    var aside = panel();
    if (!aside || event.detail.target !== aside) { return; }
    if (aside.dataset.shown) { aside.dataset.url = aside.dataset.shown; }
    else { delete aside.dataset.url; }
    mark(aside.dataset.shown);
  });

  document.addEventListener("dblclick", function (event) {
    var row = event.target.closest("#list-rows tr[data-href]");
    if (!row) { return; }
    window.location.href = row.dataset.href;
  });

  // Стрелки — только когда строка уже выбрана и фокус не в поле ввода
  // или меню: там у клавиш своё дело. Над открытым снимком (lightbox.js)
  // стрелки тоже не трогаем — он поверх страницы
  document.addEventListener("keydown", function (event) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") { return; }
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) { return; }
    var focus = document.activeElement;
    if (focus && focus !== document.body
        && !focus.closest("#list-rows, #list-preview")) { return; }
    var lightbox = document.querySelector(".lightbox");
    if (lightbox && !lightbox.hidden) { return; }

    var current = document.querySelector("#list-rows tr.is-previewed");
    if (!current) { return; }
    var next = event.key === "ArrowDown"
      ? current.nextElementSibling : current.previousElementSibling;
    if (!next || !next.matches("tr[data-href]")) { return; }
    event.preventDefault();
    if (OY.openPreview(next)) { next.scrollIntoView({ block: "nearest" }); }
  });
})();
