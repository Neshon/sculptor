/* Высота списка — ровно заданное число строк, сколько бы их ни пришло.
 *
 * Окошко таблицы всегда высотой в N строк (25). Строк больше — остальные
 * прокручиваются внутри; раньше при 50 и больше на странице таблица росла
 * до потолка из CSS (100vh − 18rem, .table-wrap в app.css) и вытягивала
 * за собой и список, и краткую карточку справа. Строк меньше — на
 * последней странице, в узком фильтре — под ними пустое место, а не
 * короткая таблица: переключатель страниц под окошком стоит на одном
 * месте, и листать можно, не ловя его мышью заново.
 *
 * Включается атрибутом на обёртке таблицы:
 *
 *     <div class="table-wrap table-wrap--list" data-rows="25">
 *
 * Высоту меряет скрипт, а не CSS: строка — это ячейки разными шрифтами и
 * межстрочными интервалами, выровненные по базовой линии, и её высота
 * дробная (34,79 px при масштабе 150 %). Формула в CSS разошлась бы с ней
 * на пару пикселей на строку, и 25-я строка обрезалась бы. Скрипт кладёт
 * высоту в --rows-h; потолок из CSS остаётся — на низком экране окошко
 * ниже 25 строк. Без скрипта таблица по высоте содержимого, как раньше.
 */
(function () {
  "use strict";

  function fit(wrap) {
    var limit = parseInt(wrap.getAttribute("data-rows"), 10);
    var rows = wrap.querySelectorAll("tbody tr");
    if (!limit || !rows.length) {
      wrap.style.removeProperty("--rows-h");
      return;
    }
    var shown = Math.min(rows.length, limit);
    var first = rows[0].getBoundingClientRect();
    var last = rows[shown - 1].getBoundingClientRect();
    // Недостающие до предела строки — по средней высоте пришедших: строки
    // списка в одну линию (nowrap в app.css) и все одной высоты. Если не
    // нашлось ничего, в таблице невидимая строка-образец (.rows-probe в
    // list.html) — меряем по ней
    var missing = (limit - shown) * (last.bottom - first.top) / shown;
    // + прокрутка внутри: мерим от верха таблицы, а не от видимого края.
    // + всё, что у обёртки ниже содержимого, — горизонтальная полоса
    // прокрутки, когда описанию не хватает места (--desc-min в app.css):
    // без неё она закрыла бы последнюю строку
    var below = wrap.offsetHeight - wrap.clientHeight;
    var height = last.bottom - wrap.getBoundingClientRect().top +
      wrap.scrollTop + missing + below;
    wrap.style.setProperty("--rows-h", Math.ceil(height) + "px");
  }

  // Внутри root — страница целиком или вставленный кусок (htmx-setup.js).
  // Переход по страницам меняет только строки (#list-rows), и root тогда
  // внутри обёртки — её ищем вверх. Новая страница начинается с первой
  // строки, а не с той глубины, где остановилась прокрутка прошлой
  function start(root) {
    root = root || document;
    if (root.closest) {
      var outer = root.closest("[data-rows]");
      if (outer) { fit(outer); outer.scrollTop = 0; return; }
    }
    root.querySelectorAll("[data-rows]").forEach(fit);
  }

  window.OY = window.OY || {};
  window.OY.rows = start;

  start(document);
  // шрифт Roboto Mono приходит позже разметки и меняет высоту строк
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () { start(document); });
  }
  // заголовки колонок на узком окне переносятся, и шапка таблицы растёт
  var pending;
  window.addEventListener("resize", function () {
    clearTimeout(pending);
    pending = setTimeout(function () { start(document); }, 150);
  });
})();
