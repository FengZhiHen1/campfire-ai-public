// 检验「帧驱动滚动是否真的发生」：比对同一镜头内不同帧的设备屏幕区像素。
// 若 scrollY 生效，内容会整体上移；若为 no-op，两帧的设备内容位置相同。
// 只读 PNG。
import fs from 'node:fs';
import {PNG} from 'pngjs';

function read(file) {
  return PNG.sync.read(fs.readFileSync(file));
}

function rowSignature(png, y, x0, x1) {
  const {width, data} = png;
  let sum = 0;
  for (let x = x0; x < x1; x += 1) {
    const i = (width * y + x) << 2;
    sum += data[i] + data[i + 1] + data[i + 2];
  }
  return sum;
}

// 找屏幕区内容的竖直范围：与纯背景色不同的行
function contentTop(png, x0, x1, y0, y1) {
  const {width, data} = png;
  // 背景采样（左上角区域）
  const bi = (width * 20 + 60) << 2;
  const bg = [data[bi], data[bi + 1], data[bi + 2]];
  for (let y = y0; y < y1; y += 1) {
    let diff = 0;
    for (let x = x0; x < x1; x += 4) {
      const i = (width * y + x) << 2;
      diff += Math.abs(data[i] - bg[0]) + Math.abs(data[i + 1] - bg[1]) + Math.abs(data[i + 2] - bg[2]);
    }
    if (diff > 3000) return y;
  }
  return -1;
}

const [a, b, x0s, x1s, y0s, y1s] = process.argv.slice(2);
const x0 = Number(x0s), x1 = Number(x1s), y0 = Number(y0s), y1 = Number(y1s);
const pa = read(a), pb = read(b);
console.log(`A = ${a}`);
console.log(`B = ${b}`);
console.log(`区域 x=${x0}..${x1} y=${y0}..${y1}`);
console.log(`A 内容起始行 y = ${contentTop(pa, x0, x1, y0, y1)}`);
console.log(`B 内容起始行 y = ${contentTop(pb, x0, x1, y0, y1)}`);

// 逐行签名相关性：找 A 的每一行在 B 中的最佳匹配偏移
function bestOffset(pa, pb, x0, x1, probeY) {
  const target = rowSignature(pa, probeY, x0, x1);
  let best = null;
  for (let dy = -400; dy <= 400; dy += 1) {
    const y = probeY + dy;
    if (y < y0 || y > y1) continue;
    const s = rowSignature(pb, y, x0, x1);
    const d = Math.abs(s - target);
    if (best === null || d < best.d) best = {dy, d, s};
  }
  return best;
}
for (const py of [300, 400, 500]) {
  const m = bestOffset(pa, pb, x0, x1, py);
  console.log(`A 的 y=${py} 行在 B 中最佳匹配 dy=${m === null ? 'n/a' : m.dy} (差 ${m === null ? '-' : m.d})`);
}
