import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const files = execFileSync("rg", ["--files", "app", "src", "-g", "*.tsx", "-g", "*.ts"], { encoding: "utf8" }).trim().split("\n").filter(Boolean);
const candidates = [];
const ignored = /(className|href|type|accept|method|status|priority|source|role|value|key|id|name|path|url|content-type|authorization|aria-hidden|data-)/i;
for (const file of files) {
  readFileSync(file, "utf8").split("\n").forEach((line, index) => {
    if (ignored.test(line) || /(?:t|translateStatus|translateType|translateNotification)\s*\(/.test(line)) return;
    if (/<(?:div|span|p|h[1-6]|button|label|option|th|td|section|strong|small|a)\b[^>]*>[^<>{}`]*[A-Za-z]{3}[^<>{}`]*</.test(line) || /(?:placeholder|title|aria-label)=["'][A-Za-z]/.test(line)) {
      candidates.push(`${file}:${index + 1}: ${line.trim()}`);
    }
  });
}

if (candidates.length) {
  console.warn(`Hardcoded-string review found ${candidates.length} candidate(s). Review user-facing matches:\n${candidates.join("\n")}`);
} else {
  console.log("Hardcoded-string review found no high-confidence candidates.");
}
