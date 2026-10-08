// account.mjs — 采集脚本共用的演示账号。
//
// 为什么单独一个模块：口令不入库。此前 29 个采集脚本各自硬编码同一个口令字面量，
// 而 docs/证据/materials/light-demo-screenplay/shot-list.md 明文写着「密码不入库」——那句话
// 与实现不符。现在口令只来自环境变量，缺了就显式报错，不静默降级成一个默认口令。
//
// 账号名不带默认之外的语义：demo-parent 是文档化的虚构演示账号（见
// marketing/promo-shotcraft/DESIGN_SPEC.md 的演示种子数据一节），名字本身不敏感，
// 因此允许用 CAPTURE_ACCOUNT 覆盖，缺省即 demo-parent。
//
// 用法（在 marketing/promo-shotcraft/ 下）：
//   node --env-file=../../.env capture/capture-device-shots.mjs
// 或先在 shell 里设置 CAPTURE_PASSWORD 再直接跑脚本。

/** 演示账号名；非敏感，可被 CAPTURE_ACCOUNT 覆盖。 */
const DEFAULT_ACCOUNT_NAME = 'demo-parent';

/**
 * 取采集用的演示账号。
 *
 * 前置: 环境变量 CAPTURE_PASSWORD 非空（CAPTURE_ACCOUNT 可选）
 * 后置: 返回 { name, password }
 * 异常: 缺 CAPTURE_PASSWORD 时抛出，错误消息给出配置方式
 */
export function captureAccount() {
  const password = process.env.CAPTURE_PASSWORD;
  if (password === undefined || password === '') {
    throw new Error(
      '缺少 CAPTURE_PASSWORD：采集脚本不再内置演示口令。'
        + '请在仓库根 .env 里设置 CAPTURE_PASSWORD，'
        + '并用 node --env-file=../../.env capture/<脚本>.mjs 运行。',
    );
  }
  return { name: process.env.CAPTURE_ACCOUNT ?? DEFAULT_ACCOUNT_NAME, password };
}
