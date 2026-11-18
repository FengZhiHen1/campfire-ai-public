import { expect, type Page } from '@playwright/test';

/** 记录应用实际使用的系统字体栈。各设备选择的具体汉字字形允许不同。 */
export async function readSystemFontStack(page: Page): Promise<string> {
  const stack = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
  expect(stack, '构建产物的正文字体应使用系统字体栈').toMatch(/^system-ui,/);
  return stack;
}
