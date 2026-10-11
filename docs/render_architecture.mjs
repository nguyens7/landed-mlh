// Render a local HTML file to a 1920x1080 PNG with headless Chrome.
// Usage: node shot_file.mjs <in.html> <out.png>
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const [, , input, output] = process.argv;
const profile = fs.mkdtempSync(path.join(path.dirname(output), "chrome-profile-"));
execFileSync("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", [
  "--headless=new", `--user-data-dir=${profile}`, "--hide-scrollbars", "--window-size=1920,1080",
  "--virtual-time-budget=4000", `--screenshot=${output}`, `file://${path.resolve(input)}`,
], { stdio: "ignore" });
fs.rmSync(profile, { recursive: true, force: true });
console.log("wrote", output);
