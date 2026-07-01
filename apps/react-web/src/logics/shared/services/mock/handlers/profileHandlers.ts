/**
 * 档案 + 事件 handler（12 个端点）。
 */
import type { IRequestResponse } from '../../httpClient';
import type { ProfileResponse, EventResponse } from '@campfire/ts-shared';
import { DiagnosisType, LanguageLevel, SensoryFeature, AgeRange, ProfileBehaviorType } from '@campfire/ts-shared';
import { MockDatabase } from '../mockDatabase';
import {
  handleList,
  handleGetById,
  handleCreate,
  handleUpdate,
  handleDelete,
} from './crudHelpers';

const MOCK_DATE = '2026-05-15';

let profileCounter = 3;
let eventCounter = 8;

function generateProfileId(): string {
  profileCounter++;
  return `mock-profile-${String(profileCounter).padStart(3, '0')}`;
}

function generateEventId(): string {
  eventCounter++;
  return `mock-event-${String(eventCounter).padStart(3, '0')}`;
}

function now(): string {
  return new Date().toISOString();
}

function asSensoryFeatures(value: string[]): SensoryFeature[] {
  return value.filter((v): v is SensoryFeature =>
    Object.values(SensoryFeature).includes(v as SensoryFeature),
  );
}

// ===== Profiles =====

export async function handleListProfiles(
  _options: Record<string, unknown>,
  db: MockDatabase,
): Promise<IRequestResponse> {
  const data = await handleList(db.profiles, 1, 50);
  return { data, statusCode: 200, header: {}, errMsg: 'ok' };
}

export async function handleGetProfile(
  _options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  try {
    const data = await handleGetById<ProfileResponse>(db.profiles, 'profile_id', params.id, '档案未找到');
    return { data, statusCode: 200, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '档案未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleCreateProfile(
  options: Record<string, unknown>,
  db: MockDatabase,
): Promise<IRequestResponse> {
  const body = (options.data ?? {}) as Record<string, unknown>;
  const newProfile: ProfileResponse = {
    profile_id: generateProfileId(),
    nickname: (body.nickname as string | null) ?? null,
    birth_date: (body.birth_date as string) ?? MOCK_DATE,
    age_range: (body.age_range as AgeRange) ?? AgeRange.PRESCHOOL,
    diagnosis_type: (body.diagnosis_type as DiagnosisType) ?? DiagnosisType.ASD,
    primary_behavior: (body.primary_behavior as ProfileBehaviorType) ?? ProfileBehaviorType.STEREOTYPED,
    language_level: (body.language_level as LanguageLevel | null) ?? null,
    sensory_features: Array.isArray(body.sensory_features) ? asSensoryFeatures(body.sensory_features as string[]) : [],
    triggers: (body.triggers as string[]) ?? [],
    medication_notes: (body.medication_notes as string | null) ?? null,
    is_default: db.profiles.length === 0,
    caregiver_id: 'mock-caregiver-001',
    created_at: now(),
    updated_at: now(),
  };
  await handleCreate(db.profiles, newProfile);
  return { data: newProfile, statusCode: 201, header: {}, errMsg: 'ok' };
}

export async function handleUpdateProfile(
  options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const body = (options.data ?? {}) as Partial<ProfileResponse>;
  try {
    const updated = await handleUpdate<ProfileResponse>(
      db.profiles,
      'profile_id',
      params.id,
      { ...body, updated_at: now() },
      '档案未找到',
    );
    return { data: updated, statusCode: 200, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '档案未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleDeleteProfile(
  _options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  try {
    await handleDelete(db.profiles, 'profile_id', params.id, '档案未找到');
    db.events.delete(params.id);
    return { data: undefined, statusCode: 204, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '档案未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleSetDefaultProfile(
  _options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  for (const p of db.profiles) {
    p.is_default = false;
  }
  const target = db.profiles.find((p) => p.profile_id === params.id);
  if (target) {
    target.is_default = true;
    target.updated_at = now();
  }
  return { data: undefined, statusCode: 200, header: {}, errMsg: 'ok' };
}

export async function handleInvalidateCache(): Promise<IRequestResponse> {
  return { data: undefined, statusCode: 200, header: {}, errMsg: 'ok' };
}

// ===== Events =====

export async function handleListEvents(
  _options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const events = db.events.get(params.profileId) ?? [];
  const data = await handleList(events, 1, 50);
  return { data, statusCode: 200, header: {}, errMsg: 'ok' };
}

export async function handleGetEvent(
  _options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const events = db.events.get(params.profileId) ?? [];
  try {
    const data = await handleGetById<EventResponse>(events, 'event_id', params.eventId, '事件未找到');
    return { data, statusCode: 200, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '事件未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleCreateEvent(
  options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const body = (options.data ?? {}) as Record<string, unknown>;
  const newEvent: EventResponse = {
    event_id: generateEventId(),
    profile_id: params.profileId,
    recorded_by: 'mock-caregiver-001',
    recorded_by_role: 'family',
    event_time: (body.event_time as string) ?? now(),
    behavior_type: (body.behavior_type as string) ?? '',
    severity_level: (body.severity_level as string) ?? '',
    setting: (body.setting as string | null) ?? null,
    trigger_description: (body.trigger_description as string) ?? '',
    manifestation: (body.manifestation as string) ?? '',
    intervention_tried: (body.intervention_tried as string) ?? '',
    intervention_result: (body.intervention_result as string) ?? '',
    is_professional: false,
    tags: (body.tags as string[] | null) ?? null,
    created_at: now(),
    updated_at: now(),
  };
  const events = db.events.get(params.profileId) ?? [];
  await handleCreate(events, newEvent);
  db.events.set(params.profileId, events);
  return { data: newEvent, statusCode: 201, header: {}, errMsg: 'ok' };
}

export async function handleUpdateEvent(
  options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const events = db.events.get(params.profileId) ?? [];
  const body = (options.data ?? {}) as Partial<EventResponse>;
  try {
    const updated = await handleUpdate<EventResponse>(
      events,
      'event_id',
      params.eventId,
      { ...body, updated_at: now() },
      '事件未找到',
    );
    return { data: updated, statusCode: 200, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '事件未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleDeleteEvent(
  _options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const events = db.events.get(params.profileId) ?? [];
  try {
    await handleDelete(events, 'event_id', params.eventId, '事件未找到');
    return { data: undefined, statusCode: 204, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '事件未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}
