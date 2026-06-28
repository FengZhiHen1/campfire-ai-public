/**
 * Mock 路由表 + 分发器。
 * 33 条路由按注册顺序匹配，具体模式在泛化模式之前。
 * 首次请求时自动种子化 MockDatabase。
 */
import type { IRequestResponse, RequestOptions } from '../httpClient';
import { MockDatabase } from './mockDatabase';
import {
  seedProfiles,
  seedEvents,
  seedCases,
  seedNarratives,
  seedCards,
  seedConsultations,
} from './seedData';

// ===== Handlers =====
import {
  handleConsultSubmit,
  handleConsultHistoryList,
  handleConsultHistoryDetail,
  handleLogin,
  handleRefreshToken,
  handleAuthMe,
} from './handlers/consultHandlers';
import {
  handleListProfiles,
  handleGetProfile,
  handleCreateProfile,
  handleUpdateProfile,
  handleDeleteProfile,
  handleSetDefaultProfile,
  handleInvalidateCache,
  handleListEvents,
  handleGetEvent,
  handleCreateEvent,
  handleUpdateEvent,
  handleDeleteEvent,
} from './handlers/profileHandlers';
import {
  handleCreateCase,
  handleListCases,
  handleGetCase,
  handleUpdateCase,
  handleSubmitCase,
  handleReviewCase,
  handleFetchReviewQueue,
  handleGetCard,
  handleUpdateCard,
  handleSubmitCard,
  handleListNarratives,
  handleGetNarrative,
  handleCreateNarrative,
  handleUpdateNarrative,
  handleSubmitNarrative,
  handleExtractNarrative,
} from './handlers/caseHandlers';

// ===== Types =====

type RouteHandler = (
  options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
) => Promise<IRequestResponse>;

interface RouteEntry {
  method: string;
  pattern: RegExp;
  paramKeys: string[];
  handler: RouteHandler;
}

function parseQueryString(url: string): Record<string, string> {
  const queryIndex = url.indexOf('?');
  if (queryIndex === -1) return {};
  const queryString = url.slice(queryIndex + 1);
  const params: Record<string, string> = {};
  for (const part of queryString.split('&')) {
    const eqIndex = part.indexOf('=');
    if (eqIndex === -1) continue;
    const key = decodeURIComponent(part.slice(0, eqIndex));
    const val = decodeURIComponent(part.slice(eqIndex + 1));
    params[key] = val;
  }
  return params;
}

function getPathOnly(url: string): string {
  const queryIndex = url.indexOf('?');
  return queryIndex === -1 ? url : url.slice(0, queryIndex);
}

// ===== Route Table =====
// IMPORTANT: 具体路由必须在泛化路由之前注册。
// 例如: /api/v1/cases/review-queue 必须在 /api/v1/cases/([^/]+) 之前。

const routes: RouteEntry[] = [
  // --- Consult ---
  { method: 'POST', pattern: /^\/api\/v1\/consult$/, paramKeys: [], handler: handleConsultSubmit },
  { method: 'GET', pattern: /^\/api\/v1\/consultations$/, paramKeys: [], handler: handleConsultHistoryList },
  { method: 'GET', pattern: /^\/api\/v1\/consultations\/([^/]+)$/, paramKeys: ['id'], handler: handleConsultHistoryDetail },

  // --- Profiles (7) ---
  { method: 'GET', pattern: /^\/api\/v1\/profiles$/, paramKeys: [], handler: handleListProfiles },
  { method: 'POST', pattern: /^\/api\/v1\/profiles$/, paramKeys: [], handler: handleCreateProfile },
  { method: 'GET', pattern: /^\/api\/v1\/profiles\/([^/]+)$/, paramKeys: ['id'], handler: handleGetProfile },
  { method: 'PUT', pattern: /^\/api\/v1\/profiles\/([^/]+)$/, paramKeys: ['id'], handler: handleUpdateProfile },
  { method: 'DELETE', pattern: /^\/api\/v1\/profiles\/([^/]+)$/, paramKeys: ['id'], handler: handleDeleteProfile },
  { method: 'PUT', pattern: /^\/api\/v1\/profiles\/([^/]+)\/default$/, paramKeys: ['id'], handler: handleSetDefaultProfile },
  { method: 'POST', pattern: /^\/api\/v1\/profiles\/([^/]+)\/invalidate-cache$/, paramKeys: ['id'], handler: handleInvalidateCache },

  // --- Events (5) ---
  { method: 'GET', pattern: /^\/api\/v1\/profiles\/([^/]+)\/events$/, paramKeys: ['profileId'], handler: handleListEvents },
  { method: 'POST', pattern: /^\/api\/v1\/profiles\/([^/]+)\/events$/, paramKeys: ['profileId'], handler: handleCreateEvent },
  { method: 'GET', pattern: /^\/api\/v1\/profiles\/([^/]+)\/events\/([^/]+)$/, paramKeys: ['profileId', 'eventId'], handler: handleGetEvent },
  { method: 'PUT', pattern: /^\/api\/v1\/profiles\/([^/]+)\/events\/([^/]+)$/, paramKeys: ['profileId', 'eventId'], handler: handleUpdateEvent },
  { method: 'DELETE', pattern: /^\/api\/v1\/profiles\/([^/]+)\/events\/([^/]+)$/, paramKeys: ['profileId', 'eventId'], handler: handleDeleteEvent },

  // --- Cases (7) ---
  // 具体路由在泛化路由之前！
  { method: 'GET', pattern: /^\/api\/v1\/cases\/review-queue$/, paramKeys: [], handler: handleFetchReviewQueue },
  { method: 'POST', pattern: /^\/api\/v1\/cases$/, paramKeys: [], handler: handleCreateCase },
  { method: 'GET', pattern: /^\/api\/v1\/cases$/, paramKeys: [], handler: handleListCases },
  { method: 'POST', pattern: /^\/api\/v1\/cases\/([^/]+)\/submit$/, paramKeys: ['id'], handler: handleSubmitCase },
  { method: 'POST', pattern: /^\/api\/v1\/cases\/([^/]+)\/review$/, paramKeys: ['id'], handler: handleReviewCase },
  { method: 'GET', pattern: /^\/api\/v1\/cases\/([^/]+)$/, paramKeys: ['id'], handler: handleGetCase },
  { method: 'PUT', pattern: /^\/api\/v1\/cases\/([^/]+)$/, paramKeys: ['id'], handler: handleUpdateCase },

  // --- Cards (3) ---
  { method: 'PUT', pattern: /^\/api\/v1\/cards\/([^/]+)$/, paramKeys: ['id'], handler: handleUpdateCard },
  { method: 'POST', pattern: /^\/api\/v1\/cards\/([^/]+)\/submit$/, paramKeys: ['id'], handler: handleSubmitCard },
  { method: 'GET', pattern: /^\/api\/v1\/cards\/([^/]+)$/, paramKeys: ['id'], handler: handleGetCard },

  // --- Narratives (6) ---
  { method: 'GET', pattern: /^\/api\/v1\/narratives$/, paramKeys: [], handler: handleListNarratives },
  { method: 'POST', pattern: /^\/api\/v1\/narratives$/, paramKeys: [], handler: handleCreateNarrative },
  { method: 'POST', pattern: /^\/api\/v1\/narratives\/([^/]+)\/extract$/, paramKeys: ['id'], handler: handleExtractNarrative },
  { method: 'POST', pattern: /^\/api\/v1\/narratives\/([^/]+)\/submit$/, paramKeys: ['id'], handler: handleSubmitNarrative },
  { method: 'GET', pattern: /^\/api\/v1\/narratives\/([^/]+)$/, paramKeys: ['id'], handler: handleGetNarrative },
  { method: 'PUT', pattern: /^\/api\/v1\/narratives\/([^/]+)$/, paramKeys: ['id'], handler: handleUpdateNarrative },

  // --- Auth (3) ---
  { method: 'POST', pattern: /^\/api\/v1\/auth\/login$/, paramKeys: [], handler: handleLogin },
  { method: 'POST', pattern: /^\/api\/v1\/auth\/refresh$/, paramKeys: [], handler: handleRefreshToken },
  { method: 'GET', pattern: /^\/api\/v1\/auth\/me$/, paramKeys: [], handler: handleAuthMe },
];

let isSeeded = false;

function ensureSeeded(db: MockDatabase): void {
  if (isSeeded) return;
  db.profiles = seedProfiles();
  db.events = seedEvents();
  db.cases = seedCases();
  db.narratives = seedNarratives();
  db.cards = seedCards();
  db.consultations = seedConsultations();
  isSeeded = true;
}

export async function mockRequest(options: RequestOptions): Promise<IRequestResponse> {
  const db = MockDatabase.getInstance();
  ensureSeeded(db);

  const method = (options.method ?? 'GET').toUpperCase();
  const urlPath = getPathOnly(options.url);
  const queryParams = parseQueryString(options.url);

  for (const route of routes) {
    if (route.method !== method) continue;
    const match = urlPath.match(route.pattern);
    if (!match) continue;

    // Merge path params + query params
    const params: Record<string, string> = { ...queryParams };
    route.paramKeys.forEach((key, i) => {
      const val = match[i + 1];
      if (val) params[key] = val;
    });

    // Merge request body data into options for handler
    const opts: Record<string, unknown> = {
      ...params,
      data: (options as unknown as Record<string, unknown>).data,
    };

    return route.handler(opts, db, params);
  }

  return {
    data: { detail: `Mock route not found: ${method} ${urlPath}` },
    statusCode: 404,
    header: {},
    errMsg: 'mock: route not found',
  };
}
