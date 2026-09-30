/**
 * 模块: scripts/sync-tokens
 * 职责: 把视觉契约真源 docs/design/tokens.css 复制为 apps/web/src/shared/styles/tokens.css
 * 数据来源:
 *   - docs/design/tokens.css: MUST — 视觉契约唯一权威（docs/项目结构设计.md 第 9 节）
 * 边界:
 *   - 被依赖: apps/web 的构建与测试脚本（构建前跑）
 * 禁止行为:
 *   - 禁止在实现侧定义色值与间距；本脚本只复制，不加工、不合并、不补默认值
 *   - 禁止改写真源文件（真源只读消费）
 */

import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDir, '..');
const repoRoot = resolve(webRoot, '..', '..');

/** 视觉契约真源：唯一权威，本脚本只读。 */
const SOURCE = resolve(repoRoot, 'docs', 'design', 'tokens.css');
/** 生成物落点：apps/web 侧唯一可消费的 token 文件（生成物、不手改）。 */
const TARGET = resolve(webRoot, 'src', 'shared', 'styles', 'tokens.css');

/**
 * 同步 token 文件。
 *
 * 前置: SOURCE 存在且可读
 * 后置: TARGET 内容与 SOURCE 逐字节一致；已存在且一致时不重复写盘
 * 异常: Error（真源缺失、读取失败或写盘失败）
 */
async function syncTokens() {
  const source = await readFile(SOURCE);
  const existing = await readFile(TARGET).catch(() => null);
  if (existing !== null && existing.equals(source)) {
    console.log(`token 已同步，跳过写盘：${relative(repoRoot, TARGET)}`);
  } else {
    await mkdir(dirname(TARGET), { recursive: true });
    await writeFile(TARGET, source);
    console.log(`token 已同步：${relative(repoRoot, SOURCE)} → ${relative(repoRoot, TARGET)}`);
  }
  console.log(`真源 sha256：${createHash('sha256').update(source).digest('hex')}`);
}

await syncTokens();
