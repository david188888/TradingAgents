/** Real local HTTP/SSE and publication, with synthetic sources and no live models. */
import { expect, test } from "@playwright/test";

test('Bailian model and stage selections reach an Insight run', async ({page}) => {
  await page.goto('/');
  const provider = page.getByLabel('LLM Provider');
  await expect(provider.getByRole('option', {name: '阿里云百炼 · 已配置'})).toBeAttached();
  await provider.selectOption('bailian');
  await expect(page.getByLabel('专项与挑战模型')).toHaveValue('deepseek-v4.1-flash-1017');
  await expect(page.getByLabel('综合模型', {exact: true})).toHaveValue('kimi-k3.1-pro');
  await page.getByText('分阶段模型（高级）', {exact: true}).click();
  await page.getByLabel('质疑', {exact: true}).selectOption({label: '阿里云百炼'});
  await page.getByLabel('质疑模型', {exact: true}).selectOption('kimi-k3.1-pro');
  await page.getByLabel('股票代码').fill('600803');

  const submitted = page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname === '/api/runs');
  await page.getByRole('button', {name: '开始分析', exact: true}).click();
  expect((await submitted).postDataJSON()).toMatchObject({
    llm_provider: 'bailian', quick_think_llm: 'deepseek-v4.1-flash-1017', deep_think_llm: 'kimi-k3.1-pro',
    stage_models: {challenge: {provider: 'bailian', model: 'kimi-k3.1-pro'}},
  });
  await expect(page.getByRole('article', {name: 'Insight 研究报告'})).toBeVisible({timeout: 20000});
});

for (const ticker of ['600803', '600418']) {
  test(`Insight report preserves evidence and honest rating state: ${ticker}`, async ({page, request}) => {
    await page.goto('/');
    await page.getByLabel('股票代码').fill(ticker);
    await page.getByLabel('补充关注点（可选）').fill('核查客户风险');
    await page.getByRole('button', {name:'开始分析', exact:true}).click();
    const report = page.getByRole('article', {name:'Insight 研究报告'});
    await expect(report).toBeVisible({timeout:20000});
    await expect(report.getByRole('heading', {name:'合成测试：客户结构需要持续核查。'}).first()).toBeVisible();
    await expect(report.getByRole('heading', {name:'合成测试：回应用户关注问题。'})).toBeVisible();
    if (ticker === '600418') {
      await expect(report.getByText(/暂未形成总体判断/)).toBeVisible();
      await expect(report.getByText('中性', {exact:true})).toHaveCount(0);
    } else await expect(report.getByText('中性', {exact:true})).toBeVisible();
    await report.getByText(/查看保存依据/).first().click();
    await expect(report.getByText(/定位：/).first()).toBeVisible();
    const runId = await page.locator('.native-research-page').getAttribute('data-run');
    const process = await (await request.get(`/api/runs/${runId}/reader/process`)).json();
    expect(process.workflow_version).toBe('evidence-production-v9');
    expect(process.availability).toBe('ready');
    const focus = await (await request.get(`/api/runs/${runId}/reader/focus`)).json();
    expect(focus.state).toBe('ready');
    expect(focus.insight_response).toHaveLength(1);
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({path:test.info().outputPath(`insight-${ticker}.png`), fullPage:true});
  });
}
