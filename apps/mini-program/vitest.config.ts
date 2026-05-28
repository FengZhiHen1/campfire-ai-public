import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  resolve: {
    alias: {
      '@tarojs/taro': path.resolve(__dirname, '__mocks__/taro.ts'),
    },
  },
  test: {
    globals: true,
    environment: 'node',
    include: ['src/.tmp/adversarial-tests/**/*.test.ts', 'src/logics/cases/.tmp/adversarial-tests/**/test_*.ts', 'src/logics/consult/.tmp/adversarial-tests/**/test_*.ts'],
  },
});
