/**
 * 模块: features/profile/domain/failures
 * 职责: 档案面失败的分类与界面文案——404/409/422 三种语义必须可区分
 * 数据来源:
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 1 节错误码、第 6 节失败语义
 *   - docs/design/pages/档案页.md: MUST — 第 118 行（归档文案区分于越权并引导恢复）
 * 边界:
 *   - 依赖: 无（只收状态码，不 import HTTP 客户端——application 层不得依赖传输实现）
 *   - 被依赖: features/profile 的 viewModel 与 view
 * 禁止行为:
 *   - 禁止用异常消息文本判分支（文案会漂移；判据是契约里的状态码）
 *   - 禁止把 404 与 409 合并成一句通用错误（归档对象属主需要知道原因才能去恢复）
 */

/**
 * 档案面失败的分类。
 *
 * 判别联合而不是「{ message, retryable }」这种字段袋子：`archived` 需要一条
 * 引导恢复的出路、`not-accessible` 明确不可重试，把差异压成布尔字段后
 * 界面只能靠字符串比对再猜一次。
 */
export type ProfileFailure =
  | { kind: 'unauthorized' }
  | { kind: 'not-accessible' }
  | { kind: 'object-archived' }
  | { kind: 'invalid-payload' }
  | { kind: 'unknown' };

/**
 * 按 HTTP 状态码分类。
 *
 * 只看状态码，不看响应正文里的 `detail`：正文是给人读的文案，会随修改漂移；
 * 而状态码是契约（第 1 节的错误码表）。`code` 字段（如 `object_archived`）不经
 * 共享客户端透出（它只保留 status 与 detail），因此这里以状态码为判据——
 * 本面上 409 只有 `object_archived` 一个来源。
 */
export function classifyProfileFailure(status: number): ProfileFailure {
  switch (status) {
    case 401:
      return { kind: 'unauthorized' };
    case 404:
      return { kind: 'not-accessible' };
    case 409:
      return { kind: 'object-archived' };
    case 422:
      return { kind: 'invalid-payload' };
    default:
      return { kind: 'unknown' };
  }
}

/**
 * 从任意异常对象里取出 HTTP 状态码；取不到返回 null。
 *
 * 为什么用结构化检查而不是 `instanceof HttpError`：那需要 import infrastructure
 * 的模块，而 application/domain 不得依赖传输实现（项目结构设计第 9 节）。
 * 结构化检查同时让用例与 viewModel 可以直接对普通对象断言，测试不必构造真客户端。
 */
function statusOf(error: unknown): number | null {
  if (typeof error !== 'object' || error === null) return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === 'number' ? status : null;
}

/** 把任意异常分类成档案面失败；没有状态码的（网络中断等）归 `unknown`。 */
export function failureFromError(error: unknown): ProfileFailure {
  return classifyProfileFailure(statusOf(error) ?? 0);
}

/** 失败对应的界面标题。 */export function profileFailureTitle(failure: ProfileFailure): string {
  switch (failure.kind) {
    case 'unauthorized':
      return '登录状态已失效';
    case 'not-accessible':
      return '这个对象不存在';
    case 'object-archived':
      return '这个对象已归档';
    case 'invalid-payload':
      return '这次提交没有通过校验';
    case 'unknown':
      return '暂时无法读取档案';
  }
}

/** 失败对应的说明与下一步。 */
export function profileFailureDescription(failure: ProfileFailure): string {
  switch (failure.kind) {
    case 'unauthorized':
      return '请重新登录后再试。';
    case 'not-accessible':
      return '它可能已不属于当前账号，请返回对象列表重新选择。';
    case 'object-archived':
      // 归档是属主自己的对象：说明原因并给出恢复入口（契约第 6 节）。
      return '归档的对象不能再新增记录；可以恢复使用后再补充，已有记录仍可查看与纠正。';
    case 'invalid-payload':
      return '请检查填写的内容后重新提交。';
    case 'unknown':
      return '档案读取失败，可能是网络或服务暂时不可用。';
  }
}

/** 该失败是否值得给「重试」按钮：越权与不存在重试无用（契约第 6 节）。 */
export function isRetryable(failure: ProfileFailure): boolean {
  return failure.kind === 'unknown';
}

/**
 * 行内错误的一行文案（提交失败的反馈位）。
 *
 * 与整页错误卡的区别：行内只有一行位置，因此把「标题 + 下一步」压成一句；
 * 归档这一条保留「已归档」与「恢复后可用」两个信息点，因为使用者需要知道的是
 * 「为什么不让写」与「怎么才能写」。
 */
export function profileFailureInline(failure: ProfileFailure): string {
  switch (failure.kind) {
    case 'unauthorized':
      return '登录状态已失效，请重新登录';
    case 'not-accessible':
      return '这条记录已不属于当前账号，请刷新后重试';
    case 'object-archived':
      return '这个对象已归档，恢复使用后才能新增记录';
    case 'invalid-payload':
      return '这次提交没有通过校验，请检查填写的内容';
    case 'unknown':
      return '提交没有成功，请重试';
  }
}
