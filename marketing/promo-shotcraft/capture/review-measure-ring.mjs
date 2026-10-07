// 量测探针：在渲染出的帧里定位「应急入口高亮圈」与设备内容，检验圈是否随相机缩放一起走。
// 只读 PNG，不修改任何源文件。
import fs from 'node:fs';
import {PNG} from 'pngjs';

const ACCENT = [0xc2, 0x41, 0x0c];

function nearAccent(r, g, b, tol = 42) {
  return Math.abs(r - ACCENT[0]) < tol && Math.abs(g - ACCENT[1]) < tol && Math.abs(b - ACCENT[2]) < tol;
}

// 在左侧设备区域（x 300..1000）里找「横跨很宽的 accent 行」= 细边框（高亮圈或按钮边框）
function profile(file) {
  const png = PNG.sync.read(fs.readFileSync(file));
  const {width, height, data} = png;
  const rows = [];
  for (let y = 0; y < height; y += 1) {
    let count = 0;
    let minX = Infinity;
    let maxX = -Infinity;
    for (let x = 300; x < 1010; x += 1) {
      const i = (width * y + x) << 2;
      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      if (nearAccent(r, g, b)) {
        count += 1;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
      }
    }
    if (count > 0) rows.push({y, count, minX, maxX});
  }
  // 细边框：该行 accent 像素数少但跨度大（水平直线）→ count 明显小于跨度
  const lines = rows.filter((r) => r.maxX - r.minX > 250 && r.count < (r.maxX - r.minX) * 0.6);
  // 垂直线：某列在整个高度里有大量 accent
  const cols = [];
  for (let x = 300; x < 1010; x += 1) {
    let count = 0;
    for (let y = 150; y < 620; y += 1) {
      const i = (width * y + x) << 2;
      if (nearAccent(data[i], data[i + 1], data[i + 2])) count += 1;
    }
    if (count > 60) cols.push({x, count});
  }
  return {file, horizLines: lines, vertCols: cols};
}

for (const f of process.argv.slice(2)) {
  const p = profile(f);
  console.log(`\n===== ${p.file} =====`);
  console.log('水平 accent 直线（y, 像素数, 起止 x）:');
  for (const l of p.horizLines) console.log(`  y=${l.y} n=${l.count} x=${l.minX}..${l.maxX} span=${l.maxX - l.minX}`);
  console.log('垂直 accent 线（x, 高度像素数）:');
  for (const c of p.vertCols) console.log(`  x=${c.x} h=${c.count}`);
}
