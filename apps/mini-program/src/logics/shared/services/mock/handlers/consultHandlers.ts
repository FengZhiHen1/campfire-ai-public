/**
 * 咨询 + 认证 handler（6 个端点）。
 */
import type { IRequestResponse } from '../../httpClient';
import { MockDatabase } from '../mockDatabase';
import { simulateDelay, handleList } from './crudHelpers';

let consultCounter = 0;

export async function handleConsultSubmit(
  _options: Record<string, unknown>,
  db: MockDatabase,
): Promise<IRequestResponse> {
  await simulateDelay();
  consultCounter++;
  return {
    data: { session_id: `mock-session-${consultCounter}` },
    statusCode: 200,
    header: {},
    errMsg: 'ok',
  };
}

export async function handleConsultHistoryList(
  options: Record<string, unknown>,
  db: MockDatabase,
): Promise<IRequestResponse> {
  const page = Number(options.page) || 1;
  const pageSize = Number(options.page_size) || 20;
  const data = await handleList(db.consultations, page, pageSize);
  return { data, statusCode: 200, header: {}, errMsg: 'ok' };
}

export async function handleConsultHistoryDetail(
  options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  await simulateDelay();
  const id = params.id;
  const item = db.consultations.find((c) => c.id === id);
  if (!item) {
    return { data: { detail: '咨询记录未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
  return { data: item, statusCode: 200, header: {}, errMsg: 'ok' };
}

export async function handleLogin(): Promise<IRequestResponse> {
  await simulateDelay();
  return {
    data: {
      access_token: 'mock-access-token-jwt',
      refresh_token: 'mock-refresh-token-jwt',
      token_type: 'Bearer' as const,
    },
    statusCode: 200,
    header: {},
    errMsg: 'ok',
  };
}

export async function handleRefreshToken(): Promise<IRequestResponse> {
  await simulateDelay();
  return {
    data: {
      access_token: 'mock-access-token-refreshed',
      refresh_token: 'mock-refresh-token-refreshed',
      token_type: 'Bearer' as const,
    },
    statusCode: 200,
    header: {},
    errMsg: 'ok',
  };
}

export async function handleAuthMe(): Promise<IRequestResponse> {
  await simulateDelay();
  return {
    data: {
      user_id: 'mock-caregiver-001',
      role: 'family',
      device_id: 'campfire-mock-device',
    },
    statusCode: 200,
    header: {},
    errMsg: 'ok',
  };
}
