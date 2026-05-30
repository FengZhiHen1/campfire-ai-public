import { useState, useEffect, useCallback } from 'react';
import { consultApi } from '../../consult';
import type { ConsultationHistoryListItem } from '../../consult';
import type { ProfileListItem } from '../../profiles/types';
import { listProfiles } from '../../profiles/services/profileApi';

export function useHomePage() {
  const [loading, setLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [consultHistory, setConsultHistory] = useState<ConsultationHistoryListItem[]>([]);
  const [profiles, setProfiles] = useState<ProfileListItem[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setHasError(false);
    try {
      const [historyRes, profileRes] = await Promise.all([
        consultApi.fetchHistoryList(1, 5).catch(() => ({ items: [], total: 0, page: 1, page_size: 5 })),
        listProfiles().catch(() => []),
      ]);
      setConsultHistory(historyRes.items ?? []);
      setProfiles(profileRes);
    } catch {
      setHasError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { loading, hasError, consultHistory, profiles, load };
}
