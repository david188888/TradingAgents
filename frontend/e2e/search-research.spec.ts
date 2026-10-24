/** Saved-record presentation only; source/model adapters remain offline. */
import { expect, test } from '@playwright/test';
import type { ResearchRecordResponseDTO, ResearchRecordV2DTO } from '../src/api/contracts';
import { dualSearchRecordFixture } from './fixtures/reader-fixtures';

test('saved search rounds, evidence versions and pending questions remain readable without new searches', async ({page})=>{
  let useV2 = true;
  let writesAfterPublication = 0;
  let watching = false;
  page.on('request', request=>{
    if (watching && ['POST','PUT','PATCH','DELETE'].includes(request.method())) writesAfterPublication++;
  });
  await page.route('**/api/runs/*/reader/record', async route=>{
    const response = await route.fetch();
    const body = await response.json() as ResearchRecordResponseDTO;
    if (body.state==='ready' && useV2) {
      const record = structuredClone(dualSearchRecordFixture) as ResearchRecordV2DTO;
      record.run_id = body.run_id;
      body.record = record;
    }
    await route.fulfill({status:response.status(), contentType:'application/json', body:JSON.stringify(body)});
  });
  await page.setViewportSize({width:1280,height:900});
  await page.goto('/');
  await page.getByLabel('股票代码').fill('600803');
  await page.getByLabel('分析日期').fill('2026-10-05');
  await page.getByRole('button',{name:'开始分析',exact:true}).click();
  const reader = page.locator('.question-reader');
  await expect(reader).toBeVisible({timeout:20000});
  const section = reader.getByRole('region',{name:'联网补证与专项复核',exact:true});
  await expect(section.getByText('第 3 轮补证',{exact:true})).toBeVisible();
  watching = true;
  await expect(section).toContainText('已达到三轮补搜上限');
  await section.getByText('证据版本与适用范围',{exact:true}).click();
  await expect(section).toContainText('V0');
  await reader.getByRole('button',{name:'研究过程',exact:true}).click();
  await expect(reader.getByRole('region',{name:'联网补证与专项复核',exact:true})).toContainText('第 3 轮补证');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:test.info().outputPath('search-rounds-narrow.png')});
  expect(writesAfterPublication).toBe(0);
  useV2 = false;
  watching = false;
  await page.reload();
  // Reopen the saved run; selection is intentionally not persisted across app reloads.
  await page.getByRole('button', {name:/600803/}).first().click();
  await expect(page.locator('.question-reader')).toBeVisible({timeout:20000});
  await expect(page.getByRole('region',{name:'联网补证与专项复核',exact:true})).toHaveCount(0);
});
