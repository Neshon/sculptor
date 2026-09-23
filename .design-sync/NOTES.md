# Sculptor UI в claude.ai/design — заметки к синхронизации

Проект: «Sculptor UI», https://claude.ai/design/p/b349110c-d972-439e-ac10-df7dfaa350ab

## Что это

`design-system/` — пакет `sculptor-ui`: React-обёртки над настоящей вёрсткой
сайта. Своих стилей у обёрток нет — они ставят классы из
`components/static/components/app.css`, а `build.mjs` склеивает в
`dist/styles.css` шрифт Roboto Mono, `tokens.css` и `app.css`. Поэтому
правка стилей сайта попадает в дизайн-систему при следующей синхронизации
без правок в обёртках. Django этот пакет не использует и на сервер он не
идёт.

## Как пересинхронизировать

```
npm --prefix design-system install      # один раз
$env:DS_CHROMIUM_PATH = "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
node .ds-sync/resync.mjs --config .design-sync/config.json --node-modules design-system/node_modules --entry design-system/dist/index.js --out ./ds-bundle --remote
```

Браузеры Playwright не ставились — проверка рендера идёт в установленном
Chrome через `DS_CHROMIUM_PATH`. В PowerShell вывод node нельзя обрезать
`Select-Object -First`: он убивает процесс (выход 255).

## Превью

`previews/<Имя>.tsx`, только в форме `export const X = () => (...)` — иначе
примеры не попадают в `.prompt.md`. Отдельных `.md` рядом с компонентами нет:
они вытесняют примеры.

Описания пропсов (JSDoc) держать короче ~120 знаков — длиннее обрезаются;
подробности — в JSDoc самого компонента.

## Known render warns

- `[FONT_REMOTE] "Roboto Mono"` — шрифт грузится с Google Fonts через
  `@import`; так и задумано.
- Verdana — системный шрифт, объявлен в `runtimeFontPrefixes`.

## Re-sync risks

- Адаптив `app.css`: `.cols` складывается ниже 1080 px, `.formgrid` на три
  поля — ниже 1180 px. Окно захвата по умолчанию 900 px, поэтому у
  `Columns`, `AppShell` и `FormGrid` в `config.json` широкий `viewport`.
  Новый компонент на этих сетках — туда же.
- `specs--split` раскладывается в две колонки только внутри
  `revpage__main`; варианта `split` у `Specs` поэтому нет.
- `FormGrid columns={2|1}` задаёт колонки встроенным стилем, как шаблоны
  плат (`board_form.html`, `import.html`), — такой стиль сильнее
  медиа-запросов и на узком окне не складывается. Это поведение сайта, не
  обёртки.
- `AppShell` берёт логотип из `components/static/components/logo-white.svg`:
  переименование файла сломает сборку пакета.
- Переименование классов в `app.css` обёртки не заметят — превью молча
  потеряют оформление. После таких правок смотреть снимки из
  `ds-bundle/_screenshots/review/`.
