// 决定性检验：把设备屏幕竖条（x 460..820）在帧 B 里做纵向模板匹配，求最佳 dy。
// 若帧驱动滚动生效，dy 应接近 scrollY 差；若选择器未命中，dy 只有相机 scale 量级（几十 px 内）。
import fs from 'node:fs';
import {PNG} from 'pngjs';

function load(f) {
  return PNG.sync.read(fs.readFileSync(f));
}

const X0 = 460, X1 = 820;
const Y0 = 180, Y1 = 900;

function strip(png, y) {
  const {width, data} = png;
  const row = [];
  for (let x = X0; x < X1; x += 2) {
    const i = (width * y + x) << 2;
    row.push(data[i], data[i + 1], data[i + 2]);
  }
  return row;
}

function sad(a, b) {
  let s = 0;
  for (let i = 0; i < a.length; i += 1) s += Math.abs(a[i] - b[i]);
  return s;
}

function bestShift(fileA, fileB) {
  const A = load(fileA);
  const B = load(fileB);
  const results = [];
  for (let dy = -900; dy <= 300; dy += 1) {
    let total = 0;
    let n = 0;
    for (let y = Y0; y < Y1; y += 6) {
      const yb = y + dy;
      if (yb < 0 || yb >= B.height) continue;
      total += sad(strip(A, y), strip(B, yb));
      n += 1;
    }
    if (n < 40) continue;
    results.push({dy, avg: total / n});
  }
  results.sort((p, q) => p.avg - q.avg);
  return results.slice(0, 3);
}

const [a, b, note] = process.argv.slice(2);
console.log(`A=${a}  B=${b}  ${note ?? ''}`);
for (const r of bestShift(a, b)) {
  console.log(`  dy=${r.dy}  (A 的内容出现在 B 的 y+${r.dy})  平均每像素差=${r.avg.toFixed(1)}`);
}
