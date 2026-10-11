// Package DeckGrade into out/DeckGrade-v<version>.zip (+ .sha256) and verify
// the result against the working tree. Node builtins only, no dependencies.
// Usage: node .opencode/make_zip.mjs
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)));

const FILES = {
  "DeckGrade/dist/index.js": "dist/index.js",
  "DeckGrade/main.py": "main.py",
  "DeckGrade/package.json": "package.json",
  "DeckGrade/plugin.json": "plugin.json",
  "DeckGrade/LICENSE": "LICENSE",
  "DeckGrade/README.md": "README.md",
};

const version = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8")).version;
const outDir = path.join(ROOT, "out");
const zipName = `DeckGrade-v${version}.zip`;
const zipPath = path.join(outDir, zipName);

const missing = Object.values(FILES).filter((rel) => !fs.existsSync(path.join(ROOT, rel)));
if (missing.length) {
  console.error(`missing files (run the frontend build first?): ${missing.join(", ")}`);
  process.exit(1);
}

fs.mkdirSync(outDir, { recursive: true });
for (const name of fs.readdirSync(outDir)) {
  if (name.startsWith("DeckGrade-v") && (name.endsWith(".zip") || name.endsWith(".sha256"))) {
    fs.rmSync(path.join(outDir, name));
  }
}

// --- minimal ZIP writer (deflate) ---

let crcTable;
function crc32(buf) {
  if (!crcTable) {
    crcTable = new Int32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c;
    }
  }
  let c = -1;
  for (let i = 0; i < buf.length; i++) c = crcTable[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
}

// DOS date/time for 1980-01-01 00:00:00 (deterministic output)
const DOS_TIME = 0;
const DOS_DATE = 0x0021;

function buildZip(entries) {
  const chunks = [];
  const central = [];
  let offset = 0;
  for (const { name, data } of entries) {
    const nameBuf = Buffer.from(name, "utf8");
    const raw = data;
    const compressed = zlib.deflateRawSync(raw, { level: 9 });
    const crc = crc32(raw);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4); // version needed
    local.writeUInt16LE(0, 6); // flags
    local.writeUInt16LE(8, 8); // method: deflate
    local.writeUInt16LE(DOS_TIME, 10);
    local.writeUInt16LE(DOS_DATE, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(raw.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    local.writeUInt16LE(0, 28); // extra len
    chunks.push(local, nameBuf, compressed);

    const cd = Buffer.alloc(46);
    cd.writeUInt32LE(0x02014b50, 0);
    cd.writeUInt16LE(20, 4); // version made by
    cd.writeUInt16LE(20, 6); // version needed
    cd.writeUInt16LE(0, 8); // flags
    cd.writeUInt16LE(8, 10); // method
    cd.writeUInt16LE(DOS_TIME, 12);
    cd.writeUInt16LE(DOS_DATE, 14);
    cd.writeUInt32LE(crc, 16);
    cd.writeUInt32LE(compressed.length, 20);
    cd.writeUInt32LE(raw.length, 24);
    cd.writeUInt16LE(nameBuf.length, 28);
    // extra len, comment len, disk start, internal attrs: 0
    cd.writeUInt32LE(0, 38); // external attrs
    cd.writeUInt32LE(offset, 42); // local header offset
    central.push(Buffer.concat([cd, nameBuf]));

    offset += local.length + nameBuf.length + compressed.length;
  }
  const centralBuf = Buffer.concat(central);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(centralBuf.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...chunks, centralBuf, eocd]);
}

const entries = Object.entries(FILES).map(([arc, rel]) => {
  const data = fs.readFileSync(path.join(ROOT, rel));
  console.log(`added: ${arc}`);
  return { name: arc, data };
});

fs.writeFileSync(zipPath, buildZip(entries));

const digest = crypto.createHash("sha256").update(fs.readFileSync(zipPath)).digest("hex");
fs.writeFileSync(zipPath + ".sha256", `${digest}  ${zipName}\n`);
console.log(`wrote: out/${zipName} (+ .sha256)`);

// --- verification: re-read the zip, byte-compare against the working tree ---

function readZipEntries(buf) {
  // locate EOCD (scan back from the end, no comment in our zips)
  let eocd = -1;
  for (let i = buf.length - 22; i >= 0; i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("EOCD not found");
  const count = buf.readUInt16LE(eocd + 10);
  const cdOffset = buf.readUInt32LE(eocd + 16);
  const result = [];
  let p = cdOffset;
  for (let i = 0; i < count; i++) {
    if (buf.readUInt32LE(p) !== 0x02014b50) throw new Error("bad central directory header");
    const method = buf.readUInt16LE(p + 10);
    const compSize = buf.readUInt32LE(p + 20);
    const nameLen = buf.readUInt16LE(p + 28);
    const extraLen = buf.readUInt16LE(p + 30);
    const commentLen = buf.readUInt16LE(p + 32);
    const localOffset = buf.readUInt32LE(p + 42);
    const name = buf.toString("utf8", p + 46, p + 46 + nameLen);
    const localNameLen = buf.readUInt16LE(localOffset + 26);
    const localExtraLen = buf.readUInt16LE(localOffset + 28);
    const dataStart = localOffset + 30 + localNameLen + localExtraLen;
    const raw =
      method === 8
        ? zlib.inflateRawSync(buf.subarray(dataStart, dataStart + compSize))
        : buf.subarray(dataStart, dataStart + compSize);
    result.push({ name, raw });
    p += 46 + nameLen + extraLen + commentLen;
  }
  return result;
}

const got = readZipEntries(fs.readFileSync(zipPath));
const expected = Object.fromEntries(Object.keys(FILES).map((n) => [n, null]));
if (got.length !== Object.keys(FILES).length) throw new Error(`unexpected entry count: ${got.length}`);
for (const { name, raw } of got) {
  if (name.includes("\\")) throw new Error(`zip entry has backslash separators: ${name}`);
  if (!(name in expected)) throw new Error(`unexpected zip entry: ${name}`);
  expected[name] = raw;
}
for (const [arc, rel] of Object.entries(FILES)) {
  if (expected[arc] === null) throw new Error(`zip entry missing: ${arc}`);
  if (!expected[arc].equals(fs.readFileSync(path.join(ROOT, rel)))) {
    throw new Error(`zip is stale (differs from working tree): ${arc}`);
  }
}
console.log(`zip verified OK (matches working tree): out/${zipName}`);
