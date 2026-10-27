/** Presentation fixture for section delivery; canonical publication is tested in Python. */
import { expect, test } from "@playwright/test";
import type { ResearchRecordResponseDTO } from "../src/api/contracts";

test('unfinished synthesis remains clear and inspectable on desktop and narrow screens',async({page})=>{
  await page.setViewportSize({width:1280,height:900});
  await page.route('**/api/runs/*/reader/record',async route=>{
    const response=await route.fetch();
    const body=await response.json() as ResearchRecordResponseDTO;
    if(body.state==='ready' && body.record.assessment?.schema_version==='research-assessment-v3'){
      const record=body.record, a=body.record.assessment;
      const pending=new Set(['overall',...record.challenges.map(c=>`adjudication:${c.challenge_id}`)]);
      a.investment_stance=null;a.report_status='analysis_unrated';a.completeness='partial';a.quality='LOW_CONFIDENCE';
      a.judgement='综合未完成；已保留通过校验的分段，暂未形成总体评级。';
      a.synthesis_sections={policy:'synthesis-sections-v1',sections:[...a.dimensions.map(d=>`dimension:${d.dimension}`),
        ...record.challenges.map(c=>`adjudication:${c.challenge_id}`),'overall','conditions'].map(id=>({
          section_id:id,status:pending.has(id)?'unavailable':'accepted',phase:pending.has(id)?null:'main',
          reason_code:pending.has(id)?'missing_section':null}))};
    }
    await route.fulfill({status:response.status(),contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto('/');
  await page.getByLabel('股票代码').fill('600418');
  await expect(page.getByLabel('分析日期')).toHaveCount(0);
  await page.getByRole('button',{name:'开始分析',exact:true}).click();
  const reader=page.locator('.question-reader');
  await expect(reader).toBeVisible({timeout:20000});
  await expect(reader.locator('.qr-answer')).toContainText('报告已交付 · 综合未完成');
  await expect(reader.locator('.qr-answer h3')).toHaveText('公司报告 · 暂未形成总体评级');
  const pending=reader.getByRole('complementary',{name:'未完成的综合分段'});
  await expect(pending).toContainText('总体判断 · 未完成');
  await expect(reader.getByRole('region',{name:'公司基础资料',exact:true})).toBeVisible();
  const source=reader.getByRole('region',{name:'公司基础资料',exact:true}).getByRole('button',{name:'核对保存来源 →'}).first();
  await source.click();
  await expect(page.getByRole('dialog',{name:'依据与概念解释',exact:true})).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(source).toBeFocused();
  await page.setViewportSize({width:390,height:844});
  await expect(pending).toContainText('总体判断 · 未完成');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await pending.scrollIntoViewIfNeeded();
  await page.screenshot({path:test.info().outputPath('synthesis-sections-narrow.png')});
});
