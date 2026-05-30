import { Component } from 'react';
import type { ReactNode } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';

interface ErrorBoundaryProps {
  children?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  errorMsg: string;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, errorMsg: '' };
  }

  componentDidCatch(error: Error): void {
    this.setState({ hasError: true, errorMsg: error.message || '发生了未知错误' });
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <View className='error-boundary'>
        <View className='error-boundary__icon'>
          <Text>⚠️</Text>
        </View>
        <Text className='error-boundary__title'>页面出错了</Text>
        <Text className='error-boundary__desc'>{this.state.errorMsg}</Text>
        <Button
          className='error-boundary__retry'
          onClick={() => Taro.reLaunch({ url: '/views/shared/pages/home' })}
        >
          返回首页
        </Button>
      </View>
    );
  }
}

export default ErrorBoundary;
