/* Поле даты с календарём в стиле сайта.
 *
 * Календарь родного <input type="date"> рисует браузер, и оформить его
 * нельзя: ни шрифт, ни цвета, ни тёмная тема сайта до него не доходят. Так
 * же, как с выпадающими списками (select.js), родное поле остаётся в
 * форме и хранит значение — оно отправляется, оно же остаётся
 * единственным полем, если скрипт не загрузился. Рядом появляются
 * текстовое поле «дд.мм.гггг» и кнопка с календарём.
 *
 * Значение в родное поле попадает только целой датой — набранной
 * полностью или выбранной в календаре. У родного поля каждая цифра года
 * меняла значение: «2026» по дороге проходило через 0002, 0020 и 0202, и
 * фильтр с автоотправкой уходил запросом за каждый из этих годов. Здесь
 * промежуточных значений нет, и отправку можно не откладывать.
 *
 * Меняется значение так же, как у списков: через родное поле и с
 * событиями input и change, будто выбрал человек, — на change висит
 * автоотправка фильтров (data-autosubmit, base.html).
 *
 * Календарь один на страницу и лежит в body, позиционируется fixed: поля
 * стоят и в панелях с прокруткой, и overflow: hidden обрезал бы его. С
 * HTMX поле может уйти со страницы вместе с формой — тогда календарь
 * закрывается перед заменой (beforeSwap), а фокус, если он был в поле,
 * возвращается в то же поле новой формы: иначе после выбора даты курсор
 * терялся бы на каждой смене фильтра.
 */
(function () {
  "use strict";

  var MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
                "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
  var WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  var GAP = 6;

  var counter = 0;
  var open = null;     // поле, для которого открыт календарь
  var view = null;     // первое число показанного месяца
  var focusDay = null; // день, на котором стоит фокус клавиатуры
  var cal = null;      // сам календарь, собирается при первом открытии
  var refocus = null;  // id родного поля, в которое вернуть фокус после замены

  var ICON_CALENDAR =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"' +
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"></rect>' +
    '<path d="M3.5 10h17M8 3v4M16 3v4"></path></svg>';
  var ICON_PREV =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"' +
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M15 6l-6 6 6 6"></path></svg>';
  var ICON_NEXT =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"' +
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M9 6l6 6-6 6"></path></svg>';

  // ---- даты -------------------------------------------------------------

  function pad(number) {
    return (number < 10 ? "0" : "") + number;
  }

  // Даты — местные, без часового пояса: new Date("2026-09-21") читается
  // как полночь по UTC, и восточнее Гринвича это ещё 20-е число
  function toIso(date) {
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" +
      pad(date.getDate());
  }

  function make(year, month, day) {
    var date = new Date(year, month, day);
    // 31.02 Date молча превращает в 3 марта — такую дату не принимаем
    if (date.getFullYear() !== year || date.getMonth() !== month ||
        date.getDate() !== day) { return null; }
    return date;
  }

  function fromIso(value) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    return m ? make(+m[1], +m[2] - 1, +m[3]) : null;
  }

  function toText(date) {
    return date ? pad(date.getDate()) + "." + pad(date.getMonth() + 1) + "." +
      date.getFullYear() : "";
  }

  // «21.09.2026»; с short — ещё и «21.09.26»: так дату дописывают, уходя
  // из поля, а на лету две цифры года — это недонабранный год, а не 20xx
  function fromText(text, short) {
    var m = /^(\d{2})\.(\d{2})\.(\d{4}|\d{2})$/.exec(text || "");
    if (!m || (m[3].length === 2 && !short)) { return null; }
    var year = m[3].length === 2 ? 2000 + +m[3] : +m[3];
    return make(year, +m[2] - 1, +m[1]);
  }

  // Набранное — к виду «дд.мм.гггг»: точки встают сами, а точка после
  // одной цифры дня или месяца дописывает ноль («5.» → «05.»)
  function mask(raw) {
    // вставили дату из адреса или выгрузки — «2026-09-21»
    var iso = /^\s*(\d{4})-(\d{2})-(\d{2})\s*$/.exec(raw);
    if (iso) { return iso[3] + "." + iso[2] + "." + iso[1]; }
    var parts = [];
    var part = "";
    for (var i = 0; i < raw.length; i++) {
      var ch = raw.charAt(i);
      if (ch >= "0" && ch <= "9") {
        if (parts.length === 2 && part.length === 4) { break; }
        part += ch;
        if (parts.length < 2 && part.length === 2) {
          parts.push(part);
          part = "";
        }
      } else if (/[.,\/\s-]/.test(ch) && parts.length < 2 && part.length === 1) {
        parts.push("0" + part);
        part = "";
      }
    }
    return parts.join(".") + (parts.length ? "." : "") + part;
  }

  function inRange(box, date) {
    var iso = toIso(date);
    return !(box.native.min && iso < box.native.min) &&
           !(box.native.max && iso > box.native.max);
  }

  // ---- поле ---------------------------------------------------------------

  function build(native) {
    var box = document.createElement("div");
    box.className = "datepick";
    native.parentNode.insertBefore(box, native);
    box.appendChild(native);

    native.classList.add("datepick__native");
    native.tabIndex = -1;
    native.setAttribute("aria-hidden", "true");

    var id = "datepick-" + (++counter);
    var text = document.createElement("input");
    text.type = "text";
    text.id = native.id ? native.id + "-text" : id;
    // классы родного поля — на видимое: от них зависит размер и вид
    text.className = (native.className.replace("datepick__native", "") +
                      " datepick__input").replace(/\s+/g, " ").trim();
    text.inputMode = "numeric";
    text.autocomplete = "off";
    text.placeholder = "дд.мм.гггг";
    text.maxLength = 10;
    text.disabled = native.disabled;
    if (native.title) { text.title = native.title; }
    if (native.getAttribute("aria-label")) {
      text.setAttribute("aria-label", native.getAttribute("aria-label"));
    }
    // подпись поля вела на скрытое теперь родное — переводим на видимое
    var caption = native.id
      ? document.querySelector('label[for="' + native.id + '"]') : null;
    if (caption) { caption.htmlFor = text.id; }
    box.appendChild(text);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "datepick__btn";
    button.disabled = native.disabled;
    button.setAttribute("aria-label", "Выбрать дату в календаре");
    button.setAttribute("aria-haspopup", "dialog");
    button.setAttribute("aria-expanded", "false");
    button.innerHTML = ICON_CALENDAR;
    box.appendChild(button);

    return {native: native, box: box, text: text, button: button,
            // подсветка «фильтр задан» — только в панели фильтров: в форме
            // заполненное поле выглядит так же, как остальные
            filter: !!native.closest(".toolbar")};
  }

  function show(box) {
    box.text.value = toText(fromIso(box.native.value));
    box.box.classList.toggle("is-set", box.filter && !!box.native.value);
    box.text.classList.remove("is-invalid");
  }

  function setValue(box, value) {
    if (box.native.value === value) { show(box); return; }
    box.native.value = value;
    show(box);
    box.native.dispatchEvent(new Event("input", {bubbles: true}));
    box.native.dispatchEvent(new Event("change", {bubbles: true}));
  }

  // Уход из поля и Enter: неполную дату дописываем или возвращаем прежнюю.
  // Оставить в поле то, чего нет в форме, значило бы показать фильтр,
  // который не применён
  function settle(box) {
    var value = box.text.value.trim();
    if (!value) { setValue(box, ""); return; }
    var date = fromText(value, true);
    if (date && inRange(box, date)) { setValue(box, toIso(date)); }
    else { show(box); }
  }

  function wire(box) {
    box.text.addEventListener("input", function (event) {
      var typing = !(event.inputType && event.inputType.indexOf("delete") === 0);
      var atEnd = box.text.selectionStart === box.text.value.length;
      // Маска — только при наборе в конце поля. При стирании она вернула
      // бы только что стёртую точку, а посреди поля — сбила бы курсор
      if (typing && atEnd) { box.text.value = mask(box.text.value); }

      var value = box.text.value.trim();
      var date = fromText(value, false);
      if (!value) {
        setValue(box, "");
      } else if (date && inRange(box, date)) {
        setValue(box, toIso(date));
      }
      // набрано полностью, а такой даты нет (31.02) — видно сразу
      box.text.classList.toggle("is-invalid",
        value.length === 10 && !(date && inRange(box, date)));
    });

    box.text.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        // форма после этого отправится как обычно — уже с дописанной датой
        settle(box);
      } else if (event.key === "ArrowDown" && (event.altKey || !box.text.value)) {
        event.preventDefault();
        openCalendar(box);
      } else if (event.key === "Escape" && open === box) {
        closeCalendar(true);
      }
    });

    box.text.addEventListener("blur", function () {
      // в календарь уходит фокус при выборе дня — это не уход из поля
      if (open === box) { return; }
      settle(box);
    });

    box.button.addEventListener("click", function () {
      if (open === box) { closeCalendar(true); } else { openCalendar(box); }
    });
  }

  function enhance(native) {
    if (native.dataset.datepick) { return; }
    native.dataset.datepick = "1";
    var box = build(native);
    show(box);
    if (!native.disabled) { wire(box); }
    if (refocus && native.id === refocus) {
      refocus = null;
      box.text.focus({preventScroll: true});
      var end = box.text.value.length;
      box.text.setSelectionRange(end, end);
    }
  }

  // ---- календарь ----------------------------------------------------------

  function buildCalendar() {
    cal = document.createElement("div");
    cal.className = "cal";
    cal.setAttribute("role", "dialog");
    cal.setAttribute("aria-label", "Выбор даты");
    cal.hidden = true;
    cal.innerHTML =
      '<div class="cal__head">' +
        '<button type="button" class="cal__nav" data-step="-1" aria-label="Предыдущий месяц">' + ICON_PREV + '</button>' +
        '<span class="cal__title" aria-live="polite"></span>' +
        '<button type="button" class="cal__nav" data-step="1" aria-label="Следующий месяц">' + ICON_NEXT + '</button>' +
      '</div>' +
      '<div class="cal__grid" role="grid"></div>' +
      '<div class="cal__foot">' +
        '<button type="button" class="cal__link" data-act="today">Сегодня</button>' +
        '<button type="button" class="cal__link" data-act="clear">Очистить</button>' +
      '</div>';
    document.body.appendChild(cal);

    cal.addEventListener("click", function (event) {
      if (!open) { return; }
      var nav = event.target.closest(".cal__nav");
      var day = event.target.closest(".cal__day");
      var act = event.target.closest("[data-act]");
      if (nav) {
        moveView(+nav.dataset.step);
      } else if (day && !day.disabled) {
        pick(fromIso(day.dataset.date));
      } else if (act && act.dataset.act === "today") {
        var today = new Date();
        today = make(today.getFullYear(), today.getMonth(), today.getDate());
        if (inRange(open, today)) { pick(today); }
      } else if (act && act.dataset.act === "clear") {
        var box = open;
        closeCalendar(true);
        setValue(box, "");
      }
    });

    cal.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeCalendar(true);
        return;
      }
      if (!event.target.classList.contains("cal__day")) { return; }
      var shift = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7}[event.key];
      if (shift) {
        event.preventDefault();
        moveFocus(new Date(focusDay.getFullYear(), focusDay.getMonth(),
                           focusDay.getDate() + shift));
      } else if (event.key === "PageUp" || event.key === "PageDown") {
        event.preventDefault();
        var step = event.key === "PageUp" ? -1 : 1;
        var target = new Date(focusDay.getFullYear(), focusDay.getMonth() + step, 1);
        // 31 марта минус месяц — это 28 февраля, а не 3 марта
        var last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
        target.setDate(Math.min(focusDay.getDate(), last));
        moveFocus(target);
      }
    });

    // фокус ушёл из календаря не в своё поле (Tab дальше по странице) —
    // календарь закрывается, как и выпадающий список
    cal.addEventListener("focusout", function (event) {
      if (!open) { return; }
      var next = event.relatedTarget;
      if (next && (cal.contains(next) || open.box.contains(next))) { return; }
      if (!next) { return; }  // щелчок мимо обрабатывает mousedown ниже
      var box = open;
      closeCalendar(false);
      settle(box);
    });
  }

  function render() {
    var box = open;
    var chosen = fromIso(box.native.value);
    var now = new Date();
    var today = toIso(new Date(now.getFullYear(), now.getMonth(), now.getDate()));

    cal.querySelector(".cal__title").textContent =
      MONTHS[view.getMonth()] + " " + view.getFullYear();

    var grid = cal.querySelector(".cal__grid");
    var html = WEEKDAYS.map(function (name) {
      return '<span class="cal__weekday" role="columnheader">' + name + "</span>";
    }).join("");

    // неделя начинается с понедельника: getDay() считает с воскресенья
    var offset = (view.getDay() + 6) % 7;
    for (var i = 0; i < 42; i++) {
      var date = new Date(view.getFullYear(), view.getMonth(), 1 - offset + i);
      var iso = toIso(date);
      var classes = ["cal__day"];
      if (date.getMonth() !== view.getMonth()) { classes.push("is-other"); }
      if (iso === today) { classes.push("is-today"); }
      var selected = chosen && iso === toIso(chosen);
      if (selected) { classes.push("is-selected"); }
      var focused = focusDay && iso === toIso(focusDay);
      html += '<button type="button" class="' + classes.join(" ") + '"' +
        ' data-date="' + iso + '" tabindex="' + (focused ? "0" : "-1") + '"' +
        ' aria-label="' + toText(date) + '"' +
        (selected ? ' aria-pressed="true"' : "") +
        (inRange(box, date) ? "" : " disabled") + ">" +
        date.getDate() + "</button>";
    }
    grid.innerHTML = html;
  }

  function moveView(step) {
    view = new Date(view.getFullYear(), view.getMonth() + step, 1);
    // фокус остаётся на том же числе нового месяца, если оно в нём есть
    var last = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
    focusDay = new Date(view.getFullYear(), view.getMonth(),
                        Math.min(focusDay.getDate(), last));
    render();
    place(open);
  }

  function moveFocus(date) {
    focusDay = date;
    if (date.getMonth() !== view.getMonth() ||
        date.getFullYear() !== view.getFullYear()) {
      view = new Date(date.getFullYear(), date.getMonth(), 1);
    }
    render();
    place(open);
    var button = cal.querySelector('.cal__day[data-date="' + toIso(date) + '"]');
    if (button) { button.focus({preventScroll: true}); }
  }

  function place(box) {
    // поле ушло со страницы вместе с формой — координаты у него нулевые
    if (!box.box.isConnected) { closeCalendar(false); return; }
    var rect = box.box.getBoundingClientRect();
    var height = cal.offsetHeight;
    var width = cal.offsetWidth;
    var below = window.innerHeight - rect.bottom - GAP;
    var above = rect.top - GAP;
    var up = below < height && above > below;
    var top = up ? Math.max(GAP, rect.top - GAP - height) : rect.bottom + GAP;
    var left = Math.min(rect.left, window.innerWidth - width - GAP);
    cal.style.top = Math.round(top) + "px";
    cal.style.left = Math.round(Math.max(GAP, left)) + "px";
  }

  function openCalendar(box) {
    if (!cal) { buildCalendar(); }
    closeCalendar(false);
    open = box;

    // Показываем месяц выбранной даты; если дата недонабрана, но уже
    // читается — её месяц; иначе текущий
    var chosen = fromIso(box.native.value) || fromText(box.text.value, true);
    var now = new Date();
    focusDay = chosen || new Date(now.getFullYear(), now.getMonth(), now.getDate());
    view = new Date(focusDay.getFullYear(), focusDay.getMonth(), 1);

    render();
    cal.hidden = false;
    box.box.classList.add("is-open");
    box.button.setAttribute("aria-expanded", "true");
    place(box);
    var button = cal.querySelector('.cal__day[tabindex="0"]');
    if (button) { button.focus({preventScroll: true}); }
  }

  function closeCalendar(focusField) {
    if (!open) { return; }
    var box = open;
    open = null;
    cal.hidden = true;
    box.box.classList.remove("is-open");
    box.button.setAttribute("aria-expanded", "false");
    if (focusField && box.text.isConnected) { box.text.focus(); }
  }

  function pick(date) {
    var box = open;
    if (!date || !inRange(box, date)) { return; }
    closeCalendar(true);
    setValue(box, toIso(date));
  }

  // ---- HTMX и страница ----------------------------------------------------

  // HTMX сейчас заменит target (htmx-setup.js). Календарь поля оттуда
  // закрываем, пока поле ещё на странице, а поле с фокусом запоминаем —
  // в новой форме фокус вернётся в него же (enhance)
  function beforeSwap(target) {
    if (!target) { return; }
    if (open && target.contains(open.box)) { closeCalendar(false); }
    var active = document.activeElement;
    if (active && active.classList.contains("datepick__input") &&
        target.contains(active)) {
      var native = active.parentNode.querySelector(".datepick__native");
      refocus = native && native.id ? native.id : null;
    }
  }

  // Внутри root — страница целиком или вставленный кусок (htmx-setup.js).
  // enhance повторную обработку отсекает сам, по data-datepick
  function start(root) {
    root = root && root.querySelectorAll ? root : document;
    if (root.matches && root.matches('input[type="date"]')) { enhance(root); }
    root.querySelectorAll('input[type="date"]').forEach(enhance);
  }

  window.OY = window.OY || {};
  window.OY.dates = start;
  window.OY.datesBeforeSwap = beforeSwap;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  // щелчок мимо календаря и мимо поля закрывает его; по своей кнопке —
  // обрабатывает она сама
  document.addEventListener("mousedown", function (event) {
    if (!open) { return; }
    if (cal.contains(event.target) || open.box.contains(event.target)) { return; }
    var box = open;
    closeCalendar(false);
    settle(box);
  });

  window.addEventListener("scroll", function () {
    if (open) { place(open); }
  }, true);
  window.addEventListener("resize", function () {
    if (open) { place(open); }
  });
})();
