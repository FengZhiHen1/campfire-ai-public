import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import './detail.scss';

export default function TicketDetail() {
  const goBack = () => {
    Taro.navigateBack();
  };

  return (
    <View className="ticket-detail-page">
      <View className="ticket-detail-navbar">
        <Button className="ticket-detail-navbar__back" onClick={goBack}>
          ←
        </Button>
        <Text className="ticket-detail-navbar__title">人工咨询</Text>
      </View>

      <View className="ticket-detail-body">
        <View className="ticket-detail-body__icon">🏗️</View>
        <Text className="ticket-detail-body__title">人工咨询通道建设中</Text>
        <Text className="ticket-detail-body__desc">
          人工咨询通道正在建设中，敬请期待。如情况紧急，请直接联系专业医疗机构。
        </Text>
      </View>

      <View className="ticket-detail-footer">
        <Button className="ticket-detail-footer__back-btn" onClick={goBack}>
          返回
        </Button>
      </View>
    </View>
  );
}
