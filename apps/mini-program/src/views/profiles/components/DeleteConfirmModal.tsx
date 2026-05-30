import { View, Text, Button, Input } from '@tarojs/components';

interface DeleteConfirmModalProps {
  visible: boolean;
  nickname: string;
  confirmName: string;
  onConfirmNameChange: (value: string) => void;
  onCancel: () => void;
  onDelete: () => void;
}

export default function DeleteConfirmModal({
  visible,
  nickname,
  confirmName,
  onConfirmNameChange,
  onCancel,
  onDelete,
}: DeleteConfirmModalProps) {
  if (!visible) return null;

  return (
    <View className="profile-delete-modal">
      <View className="profile-delete-modal__content">
        <View className="profile-delete-modal__icon">
          <Text>⚠</Text>
        </View>
        <Text className="profile-delete-modal__title">确定删除此档案？</Text>
        <Text className="profile-delete-modal__subtitle">
          档案内的所有事件记录和标签数据将被永久删除，无法恢复
        </Text>
        <Text className="profile-delete-modal__hint">
          请输入档案昵称 "{nickname}" 以确认删除
        </Text>
        <Input
          className="profile-delete-modal__input"
          value={confirmName}
          onInput={(e) => onConfirmNameChange(e.detail.value)}
          placeholder="输入档案昵称"
        />
        <View className="profile-delete-modal__actions">
          <Button
            className="profile-delete-modal__btn profile-delete-modal__btn--cancel"
            onClick={onCancel}
          >
            取消
          </Button>
          <Button
            className={`profile-delete-modal__btn profile-delete-modal__btn--delete ${confirmName !== nickname ? 'profile-delete-modal__btn--disabled' : ''}`}
            onClick={onDelete}
            disabled={confirmName !== nickname}
          >
            删除
          </Button>
        </View>
      </View>
    </View>
  );
}
