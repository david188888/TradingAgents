/** Offline real HTTP/SSE/publication/Reader flow; all sources and models mocked. */
import { expect, test } from "@playwright/test";

test('unusable synthesis still delivers a traceable basic report and specialist summary',async({page})=>{
 await page.setViewportSize({width:1280,height:900});
 await page.goto('/');
 await page.getByLabel('股票代码').fill('600418');
 await page.getByLabel('分析日期').fill('2026-09-30');
 await page.getByRole('button',{name:'开始分析',exact:true}).click();
 const reader=page.locator('.question-reader');
 await expect(reader).toBeVisible({timeout:20000});
 await expect(reader.locator('.qr-answer h3')).toHaveText('公司报告 · 暂未形成总体评级');
 await expect(reader.locator('.qr-answer')).toContainText('综合阶段未完成');
 await expect(reader.locator('.qr-answer')).not.toContainText('投资吸引力 · 证据不足');
 const basics=reader.getByRole('region',{name:'公司基础资料',exact:true});
 await expect(basics.getByText('公开公司资料 · 主营业务：汽车业务介绍（仅为离线浏览器测试合成字段）',{exact:true})).toBeVisible();
 await expect(basics.getByRole('heading',{name:/归母净利润/})).toBeVisible();
 await expect(basics.getByRole('heading',{name:'量化与行情',exact:true})).toBeVisible();
 await expect(reader.getByRole('button',{name:'来自研究综合 · 回顾产物 →'})).toHaveCount(0);
 const source=basics.getByRole('button',{name:'核对保存来源 →'}).first();
 await source.click();
 const dialog=page.getByRole('dialog',{name:'依据与概念解释',exact:true});
 await expect(dialog).toBeVisible();
 await expect(dialog).toContainText('sina.company_overview');
 await page.keyboard.press('Escape');
 await expect(source).toBeFocused();
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:test.info().outputPath('company-report-unfinished-synthesis.png')});
});
