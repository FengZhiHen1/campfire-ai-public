/**
 * 案例 + 卡片 + 叙事 handler（16 个端点）。
 */
import type { IRequestResponse } from '../../httpClient';
import type { CaseResponse, CaseReviewResponse } from '@campfire/ts-shared';
import {
  CaseStatus,
  SourceType,
  BehaviorType,
  SeverityLevel,
  SceneType,
  EvidenceLevel,
  FamilyDisplayCategory,
} from '@campfire/ts-shared';
import type { NarrativeDetail } from '../../../../cases/types';
import type { CardData } from '../../../../cases/services/cardApi';
import { MockDatabase } from '../mockDatabase';
import {
  simulateDelay,
  handleList,
  handleGetById,
  handleCreate,
  handleUpdate,
  buildPaginatedResponse,
} from './crudHelpers';
import { seedReviewQueue } from '../seedData';

let caseCounter = 6;
let narrativeCounter = 4;

function generateCaseId(): string {
  caseCounter++;
  return `mock-case-${String(caseCounter).padStart(3, '0')}`;
}

function generateNarrativeId(): string {
  narrativeCounter++;
  return `mock-narrative-${String(narrativeCounter).padStart(3, '0')}`;
}

function now(): string {
  return new Date().toISOString();
}

function asBehaviorType(value: string): BehaviorType {
  return Object.values(BehaviorType).includes(value as BehaviorType)
    ? (value as BehaviorType)
    : BehaviorType.STEREOTYPY;
}

function asSeverityLevel(value: string): SeverityLevel {
  return Object.values(SeverityLevel).includes(value as SeverityLevel)
    ? (value as SeverityLevel)
    : SeverityLevel.MODERATE;
}

function asSceneType(value: string): SceneType {
  return Object.values(SceneType).includes(value as SceneType) ? (value as SceneType) : SceneType.HOME;
}

function asEvidenceLevel(value: string): EvidenceLevel {
  return Object.values(EvidenceLevel).includes(value as EvidenceLevel)
    ? (value as EvidenceLevel)
    : EvidenceLevel.CASE_OBSERVATION;
}

function asFamilyCategory(value: string): FamilyDisplayCategory {
  return Object.values(FamilyDisplayCategory).includes(value as FamilyDisplayCategory)
    ? (value as FamilyDisplayCategory)
    : FamilyDisplayCategory.BEHAVIOR_SHAPING;
}

function asSourceType(value: string): SourceType {
  return Object.values(SourceType).includes(value as SourceType) ? (value as SourceType) : SourceType.EXPERT_WRITTEN;
}

// ===== Cases =====

export async function handleCreateCase(
  options: Record<string, unknown>,
  db: MockDatabase,
): Promise<IRequestResponse> {
  const body = (options.data ?? {}) as Record<string, unknown>;
  const newCase: CaseResponse = {
    case_id: generateCaseId(),
    status: CaseStatus.DRAFT,
    title: (body.title as string) ?? '',
    narrative: (body.narrative as string) ?? '',
    source_type: asSourceType((body.source_type as string) ?? ''),
    author_id: (body.author_id as string) ?? 'mock-expert-001',
    behavior_type: asBehaviorType((body.behavior_type as string) ?? ''),
    age_range: (body.age_range as [number, number]) ?? [3, 6],
    severity: asSeverityLevel((body.severity as string) ?? ''),
    scene: asSceneType((body.scene as string) ?? ''),
    ebp_labels: (body.ebp_labels as string[]) ?? [],
    family_category: asFamilyCategory((body.family_category as string) ?? ''),
    immediate_action: (body.immediate_action as string) ?? '',
    comforting_phrase: (body.comforting_phrase as string) ?? '',
    observation_metrics: (body.observation_metrics as string) ?? '',
    medical_criteria: (body.medical_criteria as string) ?? '',
    evidence_level: asEvidenceLevel((body.evidence_level as string) ?? ''),
    contraindications: (body.contraindications as string) ?? '',
    is_template: (body.is_template as boolean) ?? false,
    created_at: now(),
    updated_at: now(),
  };
  await handleCreate(db.cases, newCase);
  return { data: newCase, statusCode: 201, header: {}, errMsg: 'ok' };
}

export async function handleListCases(
  options: Record<string, unknown>,
  db: MockDatabase,
): Promise<IRequestResponse> {
  const page = Number(options.page) || 1;
  const pageSize = Number(options.page_size) || 15;
  const statusFilter = options.status as string | undefined;
  let filtered = db.cases;
  if (statusFilter) {
    filtered = filtered.filter((c) => c.status === statusFilter);
  }
  const data = await handleList(filtered, page, pageSize);
  return { data, statusCode: 200, header: {}, errMsg: 'ok' };
}

export async function handleGetCase(
  _options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  try {
    const data = await handleGetById<CaseResponse>(db.cases, 'case_id', params.id, '案例未找到');
    return { data, statusCode: 200, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '案例未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleUpdateCase(
  options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const body = (options.data ?? {}) as Partial<CaseResponse>;
  try {
    const updated = await handleUpdate<CaseResponse>(
      db.cases,
      'case_id',
      params.id,
      { ...body, updated_at: now() },
      '案例未找到',
    );
    return { data: updated, statusCode: 200, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '案例未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleSubmitCase(
  _options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const target = db.cases.find((c) => c.case_id === params.id);
  if (!target) {
    return { data: { detail: '案例未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
  target.status = CaseStatus.PENDING_REVIEW;
  target.updated_at = now();
  return { data: target, statusCode: 200, header: {}, errMsg: 'ok' };
}

export async function handleReviewCase(
  options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const body = (options.data ?? {}) as { decision?: string; review_comment?: string };
  const target = db.cases.find((c) => c.case_id === params.id);
  if (!target) {
    return { data: { detail: '案例未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
  const newStatus = body.decision === 'approved' ? 'approved' : 'rejected';
  target.status = newStatus as 'approved' | 'rejected' extends CaseResponse['status'] ? CaseResponse['status'] : CaseStatus.REJECTED;
  target.review_comment = body.review_comment;
  target.updated_at = now();

  const reviewResponse: CaseReviewResponse = {
    case_id: target.case_id,
    new_status: newStatus as 'approved' | 'rejected',
    ai_review_summary: {
      format_check: { status: 'pass', is_hard_gate: false },
      pii_check: { status: 'pass', is_hard_gate: true },
      required_fields_check: { status: 'pass', is_hard_gate: false },
      ebp_consistency_check: { status: 'pass', is_hard_gate: false },
      overall: 'pass',
    },
    expert_decision: body.decision ?? 'approved',
    review_comment: body.review_comment,
    reviewer_id: 'mock-reviewer-001',
    reviewed_at: now(),
  };
  return { data: reviewResponse, statusCode: 200, header: {}, errMsg: 'ok' };
}

export async function handleFetchReviewQueue(
  options: Record<string, unknown>,
): Promise<IRequestResponse> {
  const page = Number(options.page) || 1;
  const pageSize = Number(options.page_size) || 15;
  await simulateDelay();
  return {
    data: buildPaginatedResponse(seedReviewQueue(), page, pageSize),
    statusCode: 200,
    header: {},
    errMsg: 'ok',
  };
}

// ===== Cards =====

export async function handleGetCard(
  _options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  try {
    const data = await handleGetById<CardData>(db.cards, 'card_id', params.id, '卡片未找到');
    return { data, statusCode: 200, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '卡片未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleUpdateCard(
  options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const body = (options.data ?? {}) as Partial<CardData>;
  try {
    const updated = await handleUpdate<CardData>(db.cards, 'card_id', params.id, body, '卡片未找到');
    return { data: updated, statusCode: 200, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '卡片未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleSubmitCard(): Promise<IRequestResponse> {
  await simulateDelay();
  return { data: undefined, statusCode: 200, header: {}, errMsg: 'ok' };
}

// ===== Narratives =====

export async function handleListNarratives(
  options: Record<string, unknown>,
  db: MockDatabase,
): Promise<IRequestResponse> {
  const page = Number(options.page) || 1;
  const pageSize = Number(options.page_size) || 15;
  const data = await handleList(db.narratives, page, pageSize);
  return { data, statusCode: 200, header: {}, errMsg: 'ok' };
}

export async function handleGetNarrative(
  _options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  try {
    const data = await handleGetById<NarrativeDetail>(db.narratives, 'narrative_id', params.id, '叙事未找到');
    return { data, statusCode: 200, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '叙事未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleCreateNarrative(
  options: Record<string, unknown>,
  db: MockDatabase,
): Promise<IRequestResponse> {
  const body = (options.data ?? {}) as Record<string, unknown>;
  const newNarrative: NarrativeDetail = {
    narrative_id: generateNarrativeId(),
    title: (body.title as string) ?? '',
    narrative: (body.narrative as string) ?? '',
    source_type: (body.source_type as string) ?? SourceType.EXPERT_WRITTEN,
    author_id: 'mock-expert-001',
    status: 'draft',
    extraction_status: 'pending',
    extraction_error: null,
    review_comment: null,
    derived_card_ids: null,
    cards: [],
    created_at: now(),
    updated_at: now(),
  };
  await handleCreate(db.narratives, newNarrative);
  return { data: { narrative_id: newNarrative.narrative_id }, statusCode: 201, header: {}, errMsg: 'ok' };
}

export async function handleUpdateNarrative(
  options: Record<string, unknown>,
  db: MockDatabase,
  params: Record<string, string>,
): Promise<IRequestResponse> {
  const body = (options.data ?? {}) as Partial<NarrativeDetail>;
  try {
    const updated = await handleUpdate<NarrativeDetail>(
      db.narratives,
      'narrative_id',
      params.id,
      { ...body, updated_at: now() },
      '叙事未找到',
    );
    return { data: updated, statusCode: 200, header: {}, errMsg: 'ok' };
  } catch {
    return { data: { detail: '叙事未找到' }, statusCode: 404, header: {}, errMsg: 'not found' };
  }
}

export async function handleSubmitNarrative(): Promise<IRequestResponse> {
  await simulateDelay();
  return { data: { status: 'success' }, statusCode: 200, header: {}, errMsg: 'ok' };
}

export async function handleExtractNarrative(): Promise<IRequestResponse> {
  await simulateDelay();
  return {
    data: {
      status: 'completed',
      card_count: 2,
      cards: [
        { card_id: 'mock-card-extracted-1', title: '自动提取卡片 1', behavior_type: '刻板行为' },
        { card_id: 'mock-card-extracted-2', title: '自动提取卡片 2', behavior_type: '情绪崩溃' },
      ],
    },
    statusCode: 200,
    header: {},
    errMsg: 'ok',
  };
}
