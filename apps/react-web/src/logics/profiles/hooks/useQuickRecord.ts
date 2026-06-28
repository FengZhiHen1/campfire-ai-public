import { useState, useCallback } from 'react';
import { createEvent, listEvents } from '../services/eventApi';
import { showToast } from '../../shared/utils/toast';
import type { EventCreate, EventListItem } from '../types';

export interface QuickRecordFormData {
  eventTime: string;
  behaviorType: string;
  severity: string;
  setting: string;
  trigger: string;
  manifest: string;
  intervention: string;
  result: string;
}

const EMPTY_FORM: QuickRecordFormData = {
  eventTime: '',
  behaviorType: '',
  severity: '',
  setting: '',
  trigger: '',
  manifest: '',
  intervention: '',
  result: '',
};

export interface UseQuickRecordReturn {
  form: QuickRecordFormData;
  isSubmitting: boolean;
  setField: <K extends keyof QuickRecordFormData>(field: K, value: QuickRecordFormData[K]) => void;
  submit: () => Promise<boolean>;
  reset: () => void;
}

export function useQuickRecord(
  profileId: string,
  onSubmitted: (events: EventListItem[]) => void,
): UseQuickRecordReturn {
  const [form, setForm] = useState<QuickRecordFormData>(EMPTY_FORM);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const setField = useCallback(<K extends keyof QuickRecordFormData>(
    field: K,
    value: QuickRecordFormData[K],
  ) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  }, []);

  const reset = useCallback(() => {
    setForm(EMPTY_FORM);
  }, []);

  const submit = useCallback(async (): Promise<boolean> => {
    if (!form.trigger.trim() || !form.manifest.trim() || !form.behaviorType || !form.severity) {
      showToast({ title: '请填写必填项', icon: 'none' });
      return false;
    }

    setIsSubmitting(true);
    try {
      const payload: EventCreate = {
        event_time: form.eventTime || new Date().toISOString(),
        behavior_type: form.behaviorType,
        severity_level: form.severity,
        setting: form.setting || null,
        trigger_description: form.trigger.trim(),
        manifestation: form.manifest.trim(),
        intervention_tried: form.intervention.trim() || '（未记录）',
        intervention_result: form.result.trim() || '（未记录）',
        tags: null,
      };

      await createEvent(profileId, payload);
      showToast({ title: '记录已保存', icon: 'success' });

      const refreshed = await listEvents(profileId);
      onSubmitted(refreshed);
      reset();
      return true;
    } catch {
      showToast({ title: '保存失败，请重试', icon: 'none' });
      return false;
    } finally {
      setIsSubmitting(false);
    }
  }, [form, profileId, onSubmitted, reset]);

  return { form, isSubmitting, setField, submit, reset };
}
