import { NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH } from '../constants';

export interface ProfileFormValues {
  nickname: string;
  birthDate: string;
  diagnosisType: string;
  primaryBehavior: string;
}

export function validateProfileForm(values: ProfileFormValues): Record<string, string> {
  const errors: Record<string, string> = {};

  if (!values.nickname.trim()) {
    errors.nickname = '昵称不能为空';
  } else if (
    values.nickname.trim().length < NICKNAME_MIN_LENGTH ||
    values.nickname.trim().length > NICKNAME_MAX_LENGTH
  ) {
    errors.nickname = `昵称长度为 ${NICKNAME_MIN_LENGTH}-${NICKNAME_MAX_LENGTH} 个字符`;
  }

  if (!values.birthDate) {
    errors.birthDate = '请选择出生日期';
  } else if (new Date(values.birthDate) > new Date()) {
    errors.birthDate = '日期不能晚于今天';
  }

  if (!values.diagnosisType) {
    errors.diagnosisType = '请选择诊断类型';
  }

  if (!values.primaryBehavior) {
    errors.primaryBehavior = '请选择主要行为类型';
  }

  return errors;
}
