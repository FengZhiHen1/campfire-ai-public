// 决定性检验：S6 的「优先块」（浅棕底 .chat-action-priority）顶边 y 是否随 scrollY 变化。
// 若 --film-scroll 生效，顶边应随 scrollY 大幅上移；若选择器未命中（无 .phone-shell），
// 顶边只会因相机 scale 轻微移动。
import fs from 'node:fs';
import {PNG} from 'pngjs';

function blockTop(file) {
  const png = PNG.sync.read(fs.readFileSync(file));
  const {width, data} = png;
  // 取设备屏幕内一条竖线，找「浅棕块」色（R>G>B 且 R-B 明显，且不是纸底）
  const x = 640;
  const out = [];
  for (let y = 130; y < 900; y += 1) {
    const i = (width * y + x) << 2;
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    // 纸底约 (251,246,238)；优先块约 (247,235,222) 附近
    if (r > 235 && r - b > 14 && r - b < 40 && g > 220 && g < 245) out.push(y);
  }
  if (out.length === 0) return null;
  // 返回最长连续段
  let best = [out[0], out[0]], s = out[0], prev = out[0];
  for (const y of out) {
    if (y - prev <= 3) prev = y;
    else {
      if (prev - s > best[1] - best[0]) best = [s, prev];
      s = y; prev = y;
    }
  }
  if (prev - s > best[1] - best[0]) best = [s, prev];
  return best;
}

for (const f of process.argv.slice(2)) {
  const b = blockTop(f);
  console.log(`${f}  优先块竖直段 = ${b === null ? '未识别' : b[0] + '..' + b[1] + ' (h=' + (b[1] - b[0]) + ')'}`);
}
