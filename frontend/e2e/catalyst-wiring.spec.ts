/** Real HTTP/SSE/store native pipeline; synthetic 600803 inputs, no paid calls. */
import { test, expect } from "@playwright/test";

test("custom model IDs survive single/batch switching and reach native admission", async ({page}) => {
  await page.goto("/");
  await page.getByLabel("股票代码").fill("600803");
  await page.getByLabel("分析日期").fill("2026-09-30");
  await page.getByLabel("专项与挑战模型").selectOption("custom");
  await page.getByLabel("综合模型").selectOption("custom");
  await expect(page.getByRole("button",{name:"开始分析",exact:true})).toBeDisabled();
  await page.getByLabel("专项与挑战模型 ID").fill("deepseek-chat");
  await page.getByLabel("综合模型 ID").fill("deepseek-reasoner");
  const modes = page.getByRole("group",{name:"分析模式",exact:true});
  await modes.getByRole("button",{name:"批量分析",exact:true}).click();
  await expect(page.getByLabel("专项与挑战模型",{exact:true})).toHaveValue("custom");
  await expect(page.getByLabel("专项与挑战模型 ID")).toHaveValue("deepseek-chat");
  await expect(page.getByLabel("综合模型 ID")).toHaveValue("deepseek-reasoner");
  await modes.getByRole("button",{name:"单公司",exact:true}).click();
  const created = page.waitForResponse(r=>r.url().endsWith("/api/runs") && r.request().method()==="POST");
  await page.getByRole("button",{name:"开始分析",exact:true}).click();
  const response = await created;
  expect(response.status()).toBe(201);
  expect(response.request().postDataJSON()).toMatchObject({quick_think_llm:"deepseek-chat",deep_think_llm:"deepseek-reasoner"});
  await expect(page.locator(".question-reader")).toBeVisible({timeout:20000});
});

for (const viewport of [{width:1440,height:900}, {width:1280,height:800}, {width:390,height:844}, {width:720,height:450}]) {
  test(`native create/read/valuation/focus ${viewport.width}x${viewport.height}`, async ({page}) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByLabel("研究流程")).toHaveCount(0);
    await expect(page.getByLabel("研究深度")).toHaveCount(0);
    await page.getByLabel("股票代码").fill("600803");
    await page.getByLabel("分析日期").fill("2026-09-30");
    await page.getByLabel("研究问题（可选）").fill("核验经营兑现😀");
    const created = page.waitForResponse(r => r.url().endsWith("/api/runs") && r.request().method()==="POST");
    await page.getByRole("button",{name:"开始分析",exact:true}).click();
    const response=await created;
    expect(response.status()).toBe(201);
    expect(response.request().postDataJSON()).toMatchObject({research_profile:"evidence_v1",research_depth:1,research_question:"核验经营兑现😀"});
    const snapshot=await response.json();
    const brief=page.locator(".question-reader");
    await expect(brief).toBeVisible({timeout:20000});
    await expect(page.locator("[data-main-summary]")).toHaveCount(1);
    await expect(page.getByRole("img",{name:/参考区间每股/})).toBeVisible();
    await expect(page.getByText(/只有一个有效锚点，未做交叉验证。/)).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    const ref=brief.locator(".qr-evidence-entry");
    await ref.click();
    const dialog=page.getByRole("dialog",{name:"依据与概念解释"});
    await expect(dialog).toBeVisible();
    await expect(page.locator("#root")).toHaveAttribute("inert","");
    await expect(dialog.getByRole("button",{name:"关闭",exact:true})).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(ref).toBeFocused();
    await page.reload();
    await page.locator(`.history-item[data-run-id="${snapshot.run_id}"]`).getByRole("button",{name:`打开 ${snapshot.ticker} 的研究记录`,exact:true}).click();
    await expect(brief).toBeVisible();
    const read=await page.request.get(`/api/runs/${snapshot.run_id}/reader/record`);
    expect((await read.json()).record.assessment.research_question).toBe("核验经营兑现😀");
    await page.screenshot({path:test.info().outputPath(`native-${viewport.width}.png`),fullPage:true});
  });
}

for (const mode of ["catalyst_research","holding_review"]) {
  test(`native scope ${mode}`, async ({page})=>{
    await page.goto("/");
    await page.getByLabel("股票代码").fill("600803");
    await page.getByLabel("分析日期").fill("2026-09-30");
    await page.getByLabel("研究模式").selectOption(mode);
    if(mode==="holding_review") {
      await page.getByLabel("持仓数量").fill("100");
      await page.getByLabel("平均成本（每单位）").fill("20");
    }
    await page.getByRole("button",{name:"开始分析",exact:true}).click();
    await expect(page.locator(".question-reader")).toBeVisible({timeout:20000});
    if(mode==="catalyst_research") await expect(page.getByText(/展望 84 个日历日/)).toBeVisible();
    else { await page.getByRole("button",{name:"完整记录",exact:true}).click(); await expect(page.getByText("原持仓假设 · 待核查")).toHaveCount(1); }
  });
}
