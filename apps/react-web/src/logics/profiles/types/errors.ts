/**
 * PROF-07 档案数据逻辑 — 业务错误类
 *
 * 数据来源:
 *   - PROF-01 契约: MUST — ProfileLimitExceededError, ProfileConflictError 错误码
 *   - AUTH-06: SHOULD — 认证过期状态
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: hooks/, coordination/, store/
 * 禁止行为:
 *   - 禁止在错误类中包含 HTTP 状态码——那是 httpClient 层的职责
 *   - 禁止在错误消息中暴露内部实现细节
 */

export class AuthRequiredError extends Error {
  constructor(message = '请先登录') {
    super(message);
    this.name = 'AuthRequiredError';
  }
}

export class NetworkError extends Error {
  constructor(message = '加载失败，请检查网络后重试') {
    super(message);
    this.name = 'NetworkError';
  }
}

export class ServerError extends Error {
  constructor(message = '服务异常，请稍后重试') {
    super(message);
    this.name = 'ServerError';
  }
}

export class ProfileLimitExceededError extends Error {
  constructor(message = '已达到档案数量上限（5个），如需新增请先删除已有档案') {
    super(message);
    this.name = 'ProfileLimitExceededError';
  }
}

export class ProfileConflictError extends Error {
  constructor(message = '档案已被其他设备修改，请刷新后重试') {
    super(message);
    this.name = 'ProfileConflictError';
  }
}
