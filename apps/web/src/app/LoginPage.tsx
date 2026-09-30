/**
 * 模块: app/LoginPage
 * 职责: 登录页占位——页面标题、说明与「登录表单建设中」的显式提示
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: SHOULD — 页面结构与文案方向
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 4、5 节（注册凭邀请码）
 * 边界:
 *   - 依赖: 无（本包只做路由可达与占位渲染，表单落在后续包）
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止在此读取或写入凭据（会话凭据在 httpOnly cookie）
 *   - 禁止渲染空容器冒充页面
 */

import './login.css';

/**
 * 渲染登录页占位。
 *
 * 前置: 无
 * 后置: 输出标题、说明与建设中提示各一处
 * 异常: 无
 *
 * 为什么不在这里放一个「假登录」按钮：账号与邀请码校验完全在服务端（认证与账号
 * 第 4 节），前端放一个不发请求的按钮会把「未实现」显示成「可用」。
 */
export function LoginPage() {
  return (
    <section className="page login-page" aria-labelledby="login-title">
      <h1 className="page-title" id="login-title">
        登录篝火智答
      </h1>
      <p className="page-note">使用运营发放的账号与邀请码登录，登录后即可开始咨询。</p>
      <p className="status-note">登录表单尚在建设中。</p>
    </section>
  );
}
