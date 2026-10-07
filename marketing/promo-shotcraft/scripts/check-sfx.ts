// SFX 边界自检:每条 from 必须落在其所属镜头的时间范围内。
// 灵感来自 skill 的「音画同步」检查——越界的 SFX 会在错误段落响。
import {SFX} from '../src/sfx';
import {SHOTS, TOTAL} from '../src/timeline';

let errors = 0;
let warnings = 0;

console.log(`全片 ${TOTAL} 帧 (${(TOTAL / 30).toFixed(1)}s)\n`);

// 1. 每条 SFX 必须在全片范围内
for (const e of SFX) {
  if (e.from < 0 || e.from >= TOTAL) {
    console.log(`✗ 越界: ${e.comment} from=${e.from} (全片 0..${TOTAL - 1})`);
    errors++;
  }
  if (e.durationInFrames && e.from + e.durationInFrames > TOTAL) {
    console.log(
      `✗ 样本超出片尾: ${e.comment} ${e.from}+${e.durationInFrames}=${e.from + e.durationInFrames} > ${TOTAL}`,
    );
    errors++;
  }
}

// 2. 从注释里的 Sx 前缀核对所属镜头(注释约定以「Sx ...」开头)
for (const e of SFX) {
  const m = /^S(\d)\b/.exec(e.comment);
  if (!m) {
    console.log(`? 无镜头前缀: ${e.comment}`);
    warnings++;
    continue;
  }
  const id = `S${m[1]}`;
  const s = SHOTS.find((x) => x.id === id);
  if (!s) {
    console.log(`✗ 未知镜头 ${id}: ${e.comment}`);
    errors++;
    continue;
  }
  if (e.from < s.from || e.from >= s.from + s.duration) {
    console.log(
      `✗ 越段: ${e.comment} from=${e.from} 不在 ${id}[${s.from}, ${s.from + s.duration})`,
    );
    errors++;
  }
}

// 3. 每段至少一条音效(不然该段是哑的)
for (const s of SHOTS) {
  const n = SFX.filter((e) => e.from >= s.from && e.from < s.from + s.duration).length;
  const tag = n === 0 ? '✗' : n < 2 ? '!' : '·';
  if (n === 0) errors++;
  else if (n < 2) warnings++;
  console.log(`${tag} ${s.id} ${s.label.padEnd(16)} ${String(s.duration).padStart(4)}f  音效 ${n} 条`);
}

// 4. 最短间隔(过密会糊成噪音)
const sorted = [...SFX].sort((a, b) => a.from - b.from);
let minGap = Infinity;
let minAt = '';
for (let i = 1; i < sorted.length; i++) {
  const gap = sorted[i].from - sorted[i - 1].from;
  if (gap < minGap) {
    minGap = gap;
    minAt = `${sorted[i - 1].comment} → ${sorted[i].comment}`;
  }
}
console.log(`\n最近两条音效间隔 ${minGap}f (${(minGap / 30).toFixed(2)}s): ${minAt}`);

console.log(`\n结论:错误 ${errors} 条,警告 ${warnings} 条,共 ${SFX.length} 条音效`);
process.exit(errors > 0 ? 1 : 0);
