import { httpClient } from '../../shared/services/httpClient';

export interface NarrativeListItem {
  narrative_id: string;
  title: string;
  source_type: string;
  author_id: string;
  status: string;
  card_count: number;
  created_at: string;
}

export interface NarrativeDetail {
  narrative_id: string;
  title: string;
  narrative: string;
  source_type: string;
  author_id: string;
  status: string;
  derived_card_ids: string[] | null;
  cards: CardSummary[];
  created_at: string;
  updated_at: string;
}

export interface CardSummary {
  card_id: string;
  title: string;
  behavior_type: string;
  severity: string;
  scene: string;
  review_status: string;
  is_owner?: boolean;
}

const BASE = '/api/v1/narratives';

export async function listNarratives(
  scope: string = 'public',
  page: number = 1,
  pageSize: number = 20,
): Promise<{ items: NarrativeListItem[]; total: number }> {
  const res = await httpClient.request<{ items: NarrativeListItem[]; total: number }>({
    url: BASE,
    method: 'GET',
    data: { scope, page, page_size: pageSize },
  });
  return res.data;
}

export async function getNarrative(id: string): Promise<NarrativeDetail> {
  const res = await httpClient.request<NarrativeDetail>({
    url: `${BASE}/${id}`,
    method: 'GET',
  });
  return res.data;
}

export async function createNarrative(data: {
  title: string;
  narrative: string;
  source_type: string;
}): Promise<{ narrative_id: string }> {
  const res = await httpClient.request<{ narrative_id: string }>({
    url: BASE,
    method: 'POST',
    data,
    header: { 'Content-Type': 'application/json' },
  });
  return res.data;
}
