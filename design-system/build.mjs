// Сборка sculptor-ui: JS-модуль, типы и стили.
//
// Стили не хранятся в пакете — они склеиваются при каждой сборке из
// настоящих файлов сайта (components/static/components/tokens.css и
// app.css). Своя копия разошлась бы с сайтом при первой же правке, а
// дизайн-агент рисовал бы в устаревшем оформлении.

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const dist = join(here, "dist");
const siteStatic = join(here, "..", "components", "static", "components");

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });

await build({
  entryPoints: [join(here, "src", "index.ts")],
  outfile: join(dist, "index.js"),
  bundle: true,
  format: "esm",
  jsx: "automatic",
  // логотип — в самом модуле: отдельный файл картинки не доехал бы до дизайна
  loader: { ".svg": "dataurl" },
  external: ["react", "react/jsx-runtime", "react-dom"],
  target: "es2020",
});

execFileSync(process.execPath,
  [join(here, "node_modules", "typescript", "bin", "tsc"), "-p", join(here, "tsconfig.json")],
  { stdio: "inherit" });

// Roboto Mono сайт берёт из Google Fonts (<link> в base.html); здесь тот же
// адрес через @import — он обязан стоять первым в файле.
const fonts = '@import url("https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;500;700&display=swap");\n';
const header = "/* sculptor-ui: собрано из components/static/components/tokens.css и app.css. Не править — правьте исходники сайта. */\n";
const css = [
  fonts,
  header,
  readFileSync(join(siteStatic, "tokens.css"), "utf8"),
  readFileSync(join(siteStatic, "app.css"), "utf8"),
].join("\n");
writeFileSync(join(dist, "styles.css"), css);

console.log("sculptor-ui: dist/index.js, dist/*.d.ts, dist/styles.css");
