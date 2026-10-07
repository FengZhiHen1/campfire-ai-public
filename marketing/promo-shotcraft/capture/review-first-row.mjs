// 决定性检验：跟踪「设备屏幕区内第一个非背景内容行」的 y，跨帧比较。
// 若帧驱动滚动生效，内容会整体上移（该 y 减小，且卡片内容被裁掉的部分变多）。
// 只读 PNG。
import fs from 'node:fs';
import {PNG} from 'pngjs';

function load(f) {
  return PNG.sync.read(fs.readFileSync(f));
}

// 取屏幕区中心列附近的一条竖线，找与「纸底」不同的第一行
function firstContentRow(png, x, y0, y1, ref) {
  const {width, data} = png;
  for (let y = y0; y < y1; y += 1) {
    const i = (width * y + x) << 2;
    const d =
      Math.abs(data[i] - ref[0]) + Math.abs(data[i + 1] - ref[1]) + Math.abs(data[i + 2] - ref[2]);
    if (d > 40) return y;
  }
  return -1;
}

for (const f of process.argv.slice(2)) {
  const png = load(f);
  // 纸底参考色：设备外壳内部靠上的空白处
  const {width, data} = png;
  const ri = (width * 300 + 700) << 2;
  const ref = [data[ri], data[ri + 1], data[ri + 2]];
  // 屏幕区横向 460..800（避开外壳 bezel）；纵向从 150 起
  const rows = [480, 520, 560, 600, 640].map((x) => firstContentRow(png, x, 140, 900, ref));
  console.log(`${f}  纸底参考 rgb(${ref.join(',')})  各列首个内容行 y = [${rows.join(', ')}]`);
}
