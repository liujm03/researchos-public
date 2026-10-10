import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { cpSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const packagePath = require.resolve("pdfjs-dist/package.json");
const source = dirname(packagePath);
const destination = fileURLToPath(new URL("../public/pdfjs/", import.meta.url));
const { version } = JSON.parse(readFileSync(packagePath, "utf8"));
mkdirSync(destination, { recursive: true });
for (const name of ["cmaps", "standard_fonts", "wasm"]) {
  cpSync(join(source, name), join(destination, name), { recursive: true });
}
cpSync(
  join(source, "build/pdf.worker.min.mjs"),
  join(destination, "pdf.worker.min.mjs"),
);
writeFileSync(
  join(destination, "version.json"),
  JSON.stringify({ version }) + "\n",
);
console.log(`Local PDF.js ${version} worker/fonts/CMaps/WASM ready.`);
