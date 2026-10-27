/** Deterministic local sources/models; validates display, not real model quality. */
import { expect, test } from '@playwright/test';

test('premise boundaries remain readable on desktop and narrow screens', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('股票代码').fill('600418');
  await expect(page.getByLabel('分析日期')).toHaveCount(0);
  await page.getByRole('button', {name:'开始分析', exact:true}).click();
  const reader = page.locator('.question-reader');
  await expect(reader).toBeVisible({timeout:20000});
  await expect(reader.getByText('观察的来源与计算可核对；解释的含义和因果尚未证实。').first()).toBeVisible();
  const observations = reader.getByText(/已有观察与依据/).first();
  await observations.click();
  await expect(reader.locator('.qr-premise-evidence details[open]').first()).toContainText('来源转述');
  await page.setViewportSize({width:390,height:844});
  await observations.scrollIntoViewIfNeeded();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1)).toBe(true);
  await page.screenshot({path:test.info().outputPath('factual-premises-narrow.png')});
});
