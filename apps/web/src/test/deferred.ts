/**
 * 模块: src/test/deferred
 * 职责: 测试夹具——一个可外部决定何时完成/失败的挂起 Promise
 * 数据来源:
 *   - features/accounts/view/LoginPage.test.tsx 与 features/profile/viewModel/*.test.ts: MUST —
 *     这三处都要用「请求仍在途」这个状态来验证并发闸门，此前各留一份同名实现
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: 登录页用例、档案条目/对象动作的用例（只用于测试，不进生产 bundle）
 * 禁止行为:
 *   - 禁止在此伪造业务数据（夹具只造时序，不造被测数据）
 */

/** 一个可外部决定何时完成/失败的挂起 Promise。 */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
