// Generates 81x81 PNG tab bar icons for WeChat mini-program native tabBar.
// Pure Node.js — no dependencies. Run: node scripts/generate-tab-icons.cjs

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const SIZE = 81;
const OUT_DIR = path.resolve(__dirname, '..', 'src', 'assets', 'tab-icons');

// Colors
const GRAY = [0x78, 0x71, 0x6c, 0xff];   // #78716C — unselected
const AMBER = [0xf5, 0x9e, 0x0b, 0xff];   // #F59E0B — selected

// ---- low-level helpers ----

function createBuffer(size) {
  const w = size, h = size;
  return { w, h, data: Buffer.alloc(w * h * 4, 0) };
}

function setPixel(buf, x, y, color) {
  if (x < 0 || y < 0 || x >= buf.w || y >= buf.h) return;
  const i = (y * buf.w + x) * 4;
  buf.data[i] = color[0];
  buf.data[i + 1] = color[1];
  buf.data[i + 2] = color[2];
  buf.data[i + 3] = color[3];
}

function fillRect(buf, x, y, w, h, color) {
  for (let dy = 0; dy < h; dy++)
    for (let dx = 0; dx < w; dx++)
      setPixel(buf, x + dx, y + dy, color);
}

function strokeRect(buf, x, y, w, h, color, thickness) {
  fillRect(buf, x, y, w, thickness, color);          // top
  fillRect(buf, x, y + h - thickness, w, thickness, color); // bottom
  fillRect(buf, x, y, thickness, h, color);           // left
  fillRect(buf, x + w - thickness, y, thickness, h, color); // right
}

function drawCircle(buf, cx, cy, r, color, fill = false) {
  for (let dy = -r; dy <= r; dy++) {
    for (let dx = -r; dx <= r; dx++) {
      if (dx * dx + dy * dy <= r * r) {
        if (fill) {
          setPixel(buf, cx + dx, cy + dy, color);
        } else {
          // stroke only the outline (donut)
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist > r - 3 && dist <= r) {
            setPixel(buf, cx + dx, cy + dy, color);
          }
        }
      }
    }
  }
}

function drawLine(buf, x1, y1, x2, y2, color, thickness) {
  const len = Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2);
  for (let t = 0; t < len; t += 0.5) {
    const ratio = t / len;
    const cx = Math.round(x1 + (x2 - x1) * ratio);
    const cy = Math.round(y1 + (y2 - y1) * ratio);
    // draw a small square at each point for thickness
    const t2 = Math.floor(thickness / 2);
    for (let dy = -t2; dy <= t2; dy++)
      for (let dx = -t2; dx <= t2; dx++)
        setPixel(buf, cx + dx, cy + dy, color);
  }
}

// ---- icon drawing functions (coords designed for 81x81 canvas) ----

function drawHomeIcon(buf, color) {
  const c = color;
  // Roof — triangle using lines
  drawLine(buf, 40, 12, 10, 34, c, 5);  // left slope
  drawLine(buf, 40, 12, 70, 34, c, 5);  // right slope
  // Body
  strokeRect(buf, 16, 34, 48, 33, c, 5);
  // Door
  fillRect(buf, 34, 46, 14, 21, c);
  // Chimney
  fillRect(buf, 54, 15, 10, 20, c);
}

function drawConsultIcon(buf, color) {
  const c = color;
  // Speech bubble body
  fillRect(buf, 12, 14, 56, 42, c);
  // Rounded corners approximation — just use the rect, add small bumps
  // Extra pixels for rounded look
  fillRect(buf, 12, 15, 4, 40, c);
  fillRect(buf, 64, 15, 4, 40, c);
  fillRect(buf, 14, 12, 52, 4, c);
  fillRect(buf, 14, 52, 52, 4, c);
  // Remove corner pixels (simulate rounding)
  for (let i = 0; i < 6; i++) {
    for (const [ox, oy] of [[12 + i, 14 + (5 - i)], [68 - i, 14 + (5 - i)], [12 + i, 56 - (5 - i)], [68 - i, 56 - (5 - i)]]) {
      setPixel(buf, ox, oy, [0, 0, 0, 0]);
    }
  }
  // Tail triangle
  drawLine(buf, 20, 56, 14, 68, c, 5);
  drawLine(buf, 20, 56, 28, 62, c, 5);
  fillRect(buf, 14, 62, 15, 8, c);
}

function drawCasesIcon(buf, color) {
  const c = color;
  // Document body
  strokeRect(buf, 14, 14, 52, 56, c, 5);
  // Fold at top-right
  drawLine(buf, 52, 14, 52, 32, c, 5);
  drawLine(buf, 52, 32, 66, 32, c, 5);
  drawLine(buf, 52, 32, 66, 14, c, 5);
  // Text lines
  fillRect(buf, 24, 40, 32, 5, c);   // line 1
  fillRect(buf, 24, 50, 24, 5, c);   // line 2 (shorter)
  fillRect(buf, 24, 60, 28, 5, c);   // line 3
}

function drawProfileIcon(buf, color) {
  const c = color;
  // Head (circle)
  drawCircle(buf, 40, 24, 12, c, false);
  // Body
  const bodyCX = 40, bodyCY = 52, bodyRX = 22, bodyRY = 20;
  // Arc-like body shape — two curves
  drawLine(buf, bodyCX - bodyRX, 50, bodyCX + bodyRX, 50, c, 5);
  drawLine(buf, bodyCX - bodyRX, 50, bodyCX - bodyRX - 4, 72, c, 5);
  drawLine(buf, bodyCX + bodyRX, 50, bodyCX + bodyRX + 4, 72, c, 5);
  // Bottom edge
  drawLine(buf, bodyCX - bodyRX - 2, 72, bodyCX + bodyRX + 2, 72, c, 5);
  // Fill shoulders
  fillRect(buf, bodyCX - bodyRX + 3, 48, bodyRX * 2 - 6, 24, c);
}

// ---- PNG encoding ----

function encodePNG(buf) {
  // PNG signature
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

  // IHDR
  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(buf.w, 0);
  ihdrData.writeUInt32BE(buf.h, 4);
  ihdrData[8] = 8;  // bit depth
  ihdrData[9] = 6;  // color type: RGBA
  ihdrData[10] = 0; // compression
  ihdrData[11] = 0; // filter
  ihdrData[12] = 0; // interlace
  const ihdr = makeChunk('IHDR', ihdrData);

  // IDAT (raw pixel data with filter byte per row)
  const rawRows = Buffer.alloc(buf.h * (1 + buf.w * 4));
  for (let y = 0; y < buf.h; y++) {
    const rowOff = y * (1 + buf.w * 4);
    rawRows[rowOff] = 0; // filter: none
    buf.data.copy(rawRows, rowOff + 1, y * buf.w * 4, (y + 1) * buf.w * 4);
  }
  const compressed = zlib.deflateSync(rawRows, { level: 9 });
  const idat = makeChunk('IDAT', compressed);

  // IEND
  const iend = makeChunk('IEND', Buffer.alloc(0));

  return Buffer.concat([sig, ihdr, idat, iend]);
}

function makeChunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBytes = Buffer.from(type, 'ascii');
  const crcInput = Buffer.concat([typeBytes, data]);
  const crc = crc32(crcInput);
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc, 0);
  return Buffer.concat([len, typeBytes, data, crcBuf]);
}

// CRC32 implementation
function crc32(data) {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    crc ^= data[i];
    for (let j = 0; j < 8; j++) {
      if (crc & 1) crc = (crc >>> 1) ^ 0xedb88320;
      else crc >>>= 1;
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

// ---- main ----

const icons = [
  { name: 'home', draw: drawHomeIcon },
  { name: 'consult', draw: drawConsultIcon },
  { name: 'cases', draw: drawCasesIcon },
  { name: 'profile', draw: drawProfileIcon },
];

fs.mkdirSync(OUT_DIR, { recursive: true });

for (const icon of icons) {
  // Unselected (gray)
  const bufGray = createBuffer(SIZE);
  icon.draw(bufGray, GRAY);
  fs.writeFileSync(path.join(OUT_DIR, `${icon.name}.png`), encodePNG(bufGray));

  // Selected (amber)
  const bufAmber = createBuffer(SIZE);
  icon.draw(bufAmber, AMBER);
  fs.writeFileSync(path.join(OUT_DIR, `${icon.name}-active.png`), encodePNG(bufAmber));

  console.log(`  ✓ ${icon.name}.png / ${icon.name}-active.png`);
}

console.log(`\nGenerated ${icons.length * 2} icons → ${OUT_DIR}`);
