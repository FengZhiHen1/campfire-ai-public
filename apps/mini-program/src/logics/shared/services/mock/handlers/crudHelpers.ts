/**
 * 通用 CRUD 辅助函数。
 * 供所有 handler 文件复用，消除重复代码。
 */
import type { PaginatedResponse } from '@campfire/ts-shared';

const MOCK_DELAY_MS = 180;

export async function simulateDelay(): Promise<void> {
  await new Promise(resolve => setTimeout(resolve, MOCK_DELAY_MS));
}

export function buildPaginatedResponse<T>(
  items: T[],
  page: number,
  pageSize: number,
): PaginatedResponse<T> {
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const start = (page - 1) * pageSize;
  const paged = items.slice(start, start + pageSize);
  return { items: paged, total, page, page_size: pageSize, total_pages: totalPages };
}

export async function handleList<T>(
  collection: T[],
  page: number,
  pageSize: number,
): Promise<PaginatedResponse<T>> {
  await simulateDelay();
  return buildPaginatedResponse(collection, page, pageSize);
}

export async function handleGetById<T>(
  collection: T[],
  idField: string,
  idValue: string,
  notFoundMsg: string,
): Promise<T> {
  await simulateDelay();
  const item = collection.find(
    (entry) => (entry as Record<string, unknown>)[idField] === idValue,
  );
  if (!item) {
    throw new Error(notFoundMsg);
  }
  return item;
}

export async function handleCreate<T>(
  collection: T[],
  item: T,
): Promise<T> {
  await simulateDelay();
  collection.push(item);
  return item;
}

export async function handleUpdate<T>(
  collection: T[],
  idField: string,
  idValue: string,
  updates: Partial<T>,
  notFoundMsg: string,
): Promise<T> {
  await simulateDelay();
  const index = collection.findIndex(
    (entry) => (entry as Record<string, unknown>)[idField] === idValue,
  );
  if (index === -1) {
    throw new Error(notFoundMsg);
  }
  Object.assign(collection[index] as Record<string, unknown>, updates);
  return collection[index];
}

export async function handleDelete<T>(
  collection: T[],
  idField: string,
  idValue: string,
  notFoundMsg: string,
): Promise<void> {
  await simulateDelay();
  const index = collection.findIndex(
    (entry) => (entry as Record<string, unknown>)[idField] === idValue,
  );
  if (index === -1) {
    throw new Error(notFoundMsg);
  }
  collection.splice(index, 1);
}
