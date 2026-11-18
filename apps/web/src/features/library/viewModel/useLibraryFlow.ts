/**
 * 模块: features/library/viewModel/useLibraryFlow
 * 职责: 案例库浏览页的 deep-link「定位并展开」流程——按目标库别切分区、带 expand 重取、三态收口
 * 数据来源:
 *   - docs/design/pages/案例库浏览页.md: MUST — deep-link 定位（目标在库 / 已撤下 / 非法 id 按普通进入）
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 4、5 节（展开内容随列表返回、撤下三态）
 * 边界:
 *   - 依赖: features/library/application、features/library/domain/deepLink
 *   - 被依赖: features/library/viewModel/useLibraryPage
 * 禁止行为:
 *   - 禁止每次改词/换库都重新解析 deep-link（会把使用者刚收起的展开态重新撑开）
 *   - 禁止单条查询失败升级成整页错误（按普通进入处理，契约第 5 节）
 *
 * 为什么抽出来：deep-link 是一次性的进入编排（解析一次 → 切库 → 带 expand 取数 → 三态），
 * 与列表自身的检索/分页/展开状态互相独立；原实现把两者叠在同一个 hook 里，靠 `deepLinkResolved`
 * 这个 ref 闸门区分，读起来是一条隐式的时序约束。抽成独立 hook 后，时序只在这里表达。
 */

import { useEffect, useRef, useState } from 'react';

import type { LibraryKind } from '../../../shared/types/library';
import type { LibraryPort } from '../application/ports';
import { ResolveDeepLinkUseCase } from '../application/usecases';
import { type DeepLinkOutcome, type DeepLinkRequest } from '../domain/deepLink';

/** deep-link 流程依赖的列表操作（由 useLibraryPage 注入，避免两个 hook 互相 import）。 */
export interface LibraryFlowControls {
  /** 带 expand 重取第一页，并按目标库别取数。 */
  loadForDeepLink(itemId: string, library: LibraryKind): void;
}

/**
 * 解析一次 deep-link 并驱动列表进入目标态。
 *
 * @param port 资料库端口
 * @param request 进入参数（只解析一次）
 * @param controls 列表操作；请求带 itemId 时才会被调用
 * @returns 当前 deep-link 三态（`none` 表示普通进入）
 */
export function useLibraryFlow(
  port: LibraryPort,
  request: DeepLinkRequest,
  controls: LibraryFlowControls,
): DeepLinkOutcome {
  const [deepLink, setDeepLink] = useState<DeepLinkOutcome>({ kind: 'none' });
  // deep-link 只解析一次：URL 变化由路由重挂页面承担。`controls` 会随检索词/库别换身份，
  // 因此不能靠依赖数组限制次数——没有这道闸，每次按键都会重新解析一次 deep-link。
  const resolved = useRef(false);

  useEffect(() => {
    if (resolved.current) return;
    if (request.itemId === null) return;
    resolved.current = true;
    void new ResolveDeepLinkUseCase(port)
      .execute(request.itemId)
      .then((outcome) => {
        setDeepLink(outcome);
        if (outcome.kind !== 'in-library') return;
        // 「定位并展开」两半都要做：按目标条目的库别切分区，并按 `expand=<item_id>`
        // 重取本页。只置 expandedId 不动列表的话，展开内容永远不会出现——
        // 展开内容随列表返回，而不是随单条查询返回（契约第 4 节）。
        controls.loadForDeepLink(outcome.item.item_id, outcome.item.library);
      })
      .catch(() => {
        // 单条查询失败不改变整页：按普通进入处理（契约第 5 节：非法 id 不报错、不留在空页）。
        setDeepLink({ kind: 'none' });
      });
  }, [controls, port, request]);

  return deepLink;
}
