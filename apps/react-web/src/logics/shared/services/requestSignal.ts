/**
 * 请求信号工具 — createRequestSignal 与 withSignal。
 *
 * 为 httpClient 请求提供统一的超时 + 外部 AbortSignal 合并逻辑。
 * 被 cases 模块的 caseApi / cardApi / narrativeApi 等服务文件引用。
 */

/** 默认请求超时（毫秒） */
const DEFAULT_TIMEOUT_MS: number = 15000;

/**
 * 创建合并了外部 AbortSignal 和内部超时信号的 AbortSignal。
 *
 * 超时信号（默认 15 秒）确保请求不会无限挂起。
 * 外部信号（可选）允许调用方提前取消请求（如翻页竞态、组件卸载）。
 *
 * @param externalSignal - 调用方传入的可选外部 AbortSignal
 * @param timeoutMs - 超时时间（毫秒），默认 15 秒
 * @returns 合并后的 signal 和 cleanup 函数
 */
export function createRequestSignal(
  externalSignal?: AbortSignal,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(new Error('Request timeout')), timeoutMs);

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort(externalSignal.reason);
      clearTimeout(timeoutId);
    } else {
      externalSignal.addEventListener(
        'abort',
        () => {
          controller.abort(externalSignal.reason);
          clearTimeout(timeoutId);
        },
        { once: true },
      );
    }
  }

  return {
    signal: controller.signal,
    cleanup: () => clearTimeout(timeoutId),
  };
}

/**
 * 将 AbortSignal 合并到 httpClient 请求选项中。
 * React 移植版：signal 字段传递给底层 fetch API。
 */
export function withSignal<T>(
  options: T,
  signal?: AbortSignal,
): T & { signal?: AbortSignal } {
  return { ...options, signal };
}
