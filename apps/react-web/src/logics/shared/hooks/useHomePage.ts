import { useState, useEffect, useCallback } from 'react';
import { consultApi } from '../../consult';
import type { ConsultationHistoryListItem } from '../../consult';
import { useProfileStore } from '../../profiles/store/profileStore';
import { useProfile } from '../../profiles/hooks/useProfile';

export function useHomePage() {
  const [loading, setLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [consultHistory, setConsultHistory] = useState<ConsultationHistoryListItem[]>([]);

  const profiles = useProfileStore((s) => s.list);
  const listState = useProfileStore((s) => s.listState);
  const { fetchProfiles } = useProfile();

  const profilesLoading = listState === 'loading' || (listState === 'idle' && (profiles ?? []).length === 0);

  useEffect(() => {
    if (listState === 'idle' && (profiles ?? []).length === 0) {
      fetchProfiles();
    }
  }, [listState, profiles?.length, fetchProfiles]);

  const load = useCallback(async () => {
    setLoading(true);
    setHasError(false);
    try {
      const historyRes = await consultApi.fetchHistoryList(1, 5).catch(() => ({ items: [], total: 0, page: 1, page_size: 5 }));
      setConsultHistory(historyRes.items ?? []);
    } catch {
      setHasError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { loading, hasError, consultHistory, profiles, profilesLoading, load };
}
