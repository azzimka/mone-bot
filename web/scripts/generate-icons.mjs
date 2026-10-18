// Reuse the original logo. Sharp is already supplied by Next.js; no new package is needed.
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const sharp = createRequire(require.resolve("next/package.json"))("sharp");
const logo = fileURLToPath(new URL("../../logo.png", import.meta.url));
const publicDirectory = new URL("../public/", import.meta.url);
await mkdir(new URL("icons/", publicDirectory), { recursive: true });

for (const [size, name] of [
  [180, "apple-touch-icon.png"],
  [192, "icons/icon-192.png"],
  [512, "icons/icon-512.png"],
]) {
  await sharp(logo)
    .resize(size, size)
    .flatten({ background: "#ffffff" })
    .png()
    .toFile(fileURLToPath(new URL(name, publicDirectory)));
}
// Extra padding keeps the complete logo inside Android launchers' maskable safe zone.
await sharp(logo)
  .resize(448, 448)
  .extend({ top: 32, bottom: 32, left: 32, right: 32, background: "#ffffff" })
  .png()
  .toFile(fileURLToPath(new URL("icons/maskable-512.png", publicDirectory)));

const faviconFrames = [];
for (const size of [16, 32]) {
  // At favicon sizes, retain the logo's symbol without the unreadably small wordmark.
  const png = await sharp(logo)
    .extract({ left: 307, top: 198, width: 640, height: 640 })
    .resize(size, size)
    .png()
    .toBuffer();
  await writeFile(new URL(`favicon-${size}x${size}.png`, publicDirectory), png);
  faviconFrames.push({ size, png });
}
// ICO can contain PNG frames. Generate it with Node's built-in Buffer API.
const header = Buffer.alloc(6 + faviconFrames.length * 16);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(faviconFrames.length, 4);
let offset = header.length;
for (const [index, { size, png }] of faviconFrames.entries()) {
  const entry = 6 + index * 16;
  header[entry] = size;
  header[entry + 1] = size;
  header.writeUInt16LE(1, entry + 4);
  header.writeUInt16LE(32, entry + 6);
  header.writeUInt32LE(png.length, entry + 8);
  header.writeUInt32LE(offset, entry + 12);
  offset += png.length;
}
await writeFile(
  new URL("favicon.ico", publicDirectory),
  Buffer.concat([header, ...faviconFrames.map((frame) => frame.png)]),
);
console.log("Mone icons generated from the existing logo.png.");
