"""量 SFX 素材的起音延迟,并核对 `src/sfxLead.generated.ts` 是否与素材实际情况一致。

★ 为什么需要它(2026-10-08,用户报告「音画还是有些不同步」后补的):
  前几轮我一直在对齐「第几帧触发」,却从没检查过**音频文件自己开头有没有静音**。
  实测 16 个素材里 **11 个有 ≥1 帧的起音延迟**,最长的 `data-stream.mp3` 达 **488ms(14.6 帧)**。
  帧号算得再准,声音真正响起来的时刻仍被推后 —— 而且延迟**因文件而异**,所以听起来
  不是「整体偏晚」,而是「每条偏得不一样」,这正是「修了一处、别处又不对」的来源。

机理:`<Audio>` 从文件的第 0 个样本开始播。若文件开头是静音,则「触发的帧」与
「有声音的帧」之间差了这段静音。补偿办法:`<Audio trimBefore={N}>` 跳过开头 N 帧,
让**瞬态正好落在 cue 帧上**。

判据(可失败):两处不一致即 exit 1 —— ① 素材延迟变了而表没更新;② 表里的文件不存在。
"""
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path("marketing/promo-shotcraft")
SFX_DIR = ROOT / "public" / "audio" / "sfx"
TABLE = ROOT / "src" / "sfxLead.generated.ts"
FPS = 30
THRESHOLD = 0.5  # 帧;小于半帧的延迟不补偿(避免为不可听的差异改素材时序)


def measure(path: pathlib.Path) -> float:
    """返回起音延迟(秒):文件开头连续静音的时长。"""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path),
         "-af", f"silencedetect=noise=-50dB:d=0.01", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore")
    log = r.stdout + r.stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    if starts and starts[0] <= 0.005 and ends:
        return ends[0]
    return 0.0


measured = {p.stem: measure(p) for p in sorted(SFX_DIR.glob("*.mp3"))}
# ── 读回表里的值 ───────────────────────────────────────────────────────────
# ★ 必须锚定到 `export const NAME ... = { ... };` 这个**块**,不能对全文做
#   `split("SFX_CUE_LEAD")[1]` —— 该标识符在文件头注释里也出现,split 会抓到注释区
#   并把第一张表的值当成第二张的(实测踩到:11 处「不一致」全是解析错位造成的假警报)。
if not TABLE.exists():
    sys.exit(f"缺少 {TABLE} —— 请先运行本脚本的 --write 生成。")


def block(name: str) -> dict[str, int]:
    m = re.search(
        rf"export const {name}:\s*Record<string,\s*number>\s*=\s*\{{(.*?)\}};",
        TABLE.read_text(encoding="utf-8"), re.S)
    if m is None:
        sys.exit(f"✗ 表里没有 {name} —— 缺一张表会让对应那一类不同步静默复发。")
    return {k.group(1): int(k.group(2))
            for k in re.finditer(r"['\"]?([\w-]+)['\"]?\s*:\s*(\d+)", m.group(1))}


text = TABLE.read_text(encoding="utf-8")
declared = block("SFX_LEAD_FRAMES")

print(f"{'素材':<24}{'实测延迟':>10}{'表内(帧)':>10}{'实测(帧)':>10}   状态")
print("-" * 68)
problems = []
for name, lead in measured.items():
    want = 0 if lead * FPS < THRESHOLD else round(lead * FPS)
    got = declared.get(name)
    if got is None:
        problems.append(f"表里缺少 {name}")
        status = "✗ 表内缺失"
    elif got != want:
        problems.append(f"{name}: 表内 {got} 帧,实测应 {want} 帧")
        status = f"✗ 不一致(应 {want})"
    else:
        status = "✓"
    print(f"{name:<24}{lead * 1000:8.1f}ms{str(got):>10}{want:>10}   {status}")

extra = set(declared) - set(measured)
if extra:
    problems.append(f"表里有多余条目: {sorted(extra)}")

print()
if problems:
    print(f"✗ {len(problems)} 处不一致:")
    for p in problems:
        print("   " + p)
    sys.exit(1)
print(f"✓ 起音表与素材一致({len(measured)} 个素材,{sum(1 for v in declared.values() if v)} 个需要裁静音)")

# ── 第二张表:SFX_CUE_LEAD(cue 提前量)──────────────────────────────────────
#   它由「裁静音后能量到自身峰值 10% 的帧数」决定,上限 10。这里同样从素材实测,
#   与表内值比对 —— 素材换了、或有人手改了表,都必须报出来。
import numpy as np  # noqa: E402

SR = 48000


def env90(path: pathlib.Path) -> np.ndarray:
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
         "-f", "s16le", "-"],
        capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float64)
    n = SR // FPS
    return np.array([np.sqrt((a[i * n:(i + 1) * n] ** 2).mean())
                     for i in range(len(a) // n)])


part2 = None
declared2 = block("SFX_CUE_LEAD")

print()
print(f"{'素材':<24}{'表内提前':>10}{'应提前':>10}   状态")
print("-" * 56)
problems2 = []
for name, lead in measured.items():
    e = env90(SFX_DIR / f"{name}.mp3")
    peak = float(e.max())
    if peak <= 0:
        continue
    t10 = int(np.where(e >= peak * 0.10)[0][0])
    lead_frames = 0 if lead * FPS < 1 else round(lead * FPS)
    want = min(max(0, t10 - lead_frames), 10)
    got = declared2.get(name)
    if got is None:
        problems2.append(f"表里缺少 {name}")
        status = "✗ 缺失"
    elif got != want:
        problems2.append(f"{name}: 表内提前 {got} 帧,实测应 {want} 帧")
        status = f"✗ 不一致(应 {want})"
    else:
        status = "✓"
    print(f"{name:<24}{str(got):>10}{want:>10}   {status}")

if problems2:
    print(f"\n✗ {len(problems2)} 处不一致:")
    for p in problems2:
        print("   " + p)
    sys.exit(1)
print(f"\n✓ cue 提前表与素材一致({sum(1 for v in declared2.values() if v)} 个素材需要提前)")
