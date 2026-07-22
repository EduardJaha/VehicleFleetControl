import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("../src/i18n/locales/", import.meta.url);
const namespaces = ["common", "navigation", "modules", "errors"];

function flatten(value, prefix = "", output = new Map()) {
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (child && typeof child === "object" && !Array.isArray(child)) flatten(child, path, output);
    else output.set(path, child);
  }
  return output;
}

let failed = false;
for (const namespace of namespaces) {
  const dictionaries = {};
  for (const language of ["en", "sq"]) {
    const file = join(root.pathname, language, `${namespace}.json`);
    dictionaries[language] = flatten(JSON.parse(readFileSync(file, "utf8")));
  }
  for (const [source, target] of [["en", "sq"], ["sq", "en"]]) {
    const missing = [...dictionaries[source].keys()].filter((key) => !dictionaries[target].has(key));
    if (missing.length) {
      failed = true;
      console.error(`${target}/${namespace}.json is missing ${missing.length} key(s):\n${missing.map((key) => `  - ${key}`).join("\n")}`);
    }
  }
}

if (failed) process.exit(1);
console.log(`EN/SQ translation parity passed for ${namespaces.length} namespaces.`);
