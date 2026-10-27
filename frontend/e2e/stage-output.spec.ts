/** Replay actual synthetic stage APIs while the browser sees a running run. */
import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { ReaderAgentDTO, ReaderProcessDTO } from "../src/api/contracts";

test("saved stage evidence and proposal are readable before final publication",async({page,request})=>{
  await page.setViewportSize({width:1512,height:900});
  await page.goto("/");
  await page.getByLabel("股票代码").fill("600803");
  await expect(page.getByLabel("分析日期")).toHaveCount(0);
  await page.getByRole("button",{name:"开始分析",exact:true}).click();
  await expect(page.locator(".question-reader")).toBeVisible({timeout:20000});
  const runId=await page.locator(".native-research-page").getAttribute("data-run");
  const base=`/api/runs/${runId}`;
  const eventText=await (await request.get(`${base}/events`)).text();
  const events=eventText.split("\n").filter(line=>line.startsWith("data: ")).map(line=>JSON.parse(line.slice(6)));
  const boundary=events.find(e=>e.type === "role.status_changed" && e.actor_id === "native.synthesis" && e.payload.new_status === "running").sequence;
  const process=await (await request.get(`${base}/reader/process`)).json() as ReaderProcessDTO;
  process.source_sequence=boundary;process.availability="partial";process.reason_code="publication_pending";
  process.primary_selection="not_recorded";process.claim_origins=[];
  const bodies=new Map<string,ReaderAgentDTO>();
  for (const role of process.roles) {
    const body=await (await request.get(`${base}/reader/agents/${role.role_key}?source_sequence=${boundary}`)).json() as ReaderAgentDTO;
    bodies.set(role.role_key,body);role.output_availability=body.availability;role.reason_code=body.reason_code;
    role.output_sequence=boundary;
    role.output_count=body.availability !== "stage_available" ? null : role.role_key === "evidence" || ["operating_quality","event_context","market_context"].includes(role.role_key) ? body.claim_ids.length
      : role.role_key === "challenge" ? body.challenge_ids.length : null;
    if (role.role_key === "synthesis") role.status="running";
  }
  await page.route(`**${base}/**`,async route=>{
    const path=new URL(route.request().url()).pathname;
    const json=(body:unknown)=>route.fulfill({contentType:"application/json",body:JSON.stringify(body)});
    if (path.endsWith("/reader/process")) return json(process);
    if (path.includes("/reader/agents/")) return json(bodies.get(path.split("/").at(-1)!));
    if (path.endsWith("/reader/record")) return json({state:"unavailable",schema_version:1,run_id:runId,reason_code:"not_published"});
    if (path.endsWith("/events")) return route.fulfill({contentType:"text/event-stream",body:events.filter(e=>e.sequence<=boundary).map(e=>`id: ${e.sequence}\nevent: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join("")});
    const upstream=await route.fetch();const data=await upstream.json();
    if (path.endsWith("/view")) { data.terminal=false;data.view.run.status="running"; }
    return json(data);
  });
  await page.reload();
  await page.getByRole("button",{name:"打开 600803.SS 的研究记录",exact:true}).first().click();
  await expect(page.getByRole("heading",{name:"正在形成可核查的研究判断"})).toBeVisible();
  const evidence=page.getByRole("button",{name:"查看证据冻结环节与保存产物"});
  await evidence.click();
  const detail=page.getByRole("region",{name:"所选环节详情"});
  await expect(detail.getByRole("heading",{name:"已冻结的证据与检查"})).toBeVisible();
  await expect(detail.getByRole("searchbox")).toBeVisible();
  await detail.locator(".qr-saved-evidence .qr-output-card > summary").first().click();
  await expect(detail.locator(".qr-source").first()).toBeVisible();
  expect((await new AxeBuilder({page}).include('.rf-detail').analyze()).violations).toEqual([]);
  await page.screenshot({path:test.info().outputPath("stage-evidence-desktop.png")});
  await detail.getByRole("button",{name:"收起角色回顾"}).click();
  await expect(evidence).toBeFocused();
  await page.getByRole("button",{name:"查看经营研究环节与保存产物"}).click();
  await expect(detail.getByRole("heading",{name:"固定测试假设：经营改善仍需验证。"})).toBeVisible();
  await expect(detail.getByRole("status")).toContainText("尚非最终研究结论");
  await detail.locator(".qr-fact-link").first().click();
  await expect(detail.getByRole("region",{name:"阶段依据详情"})).toBeFocused();
  await page.setViewportSize({width:390,height:844});
  await detail.getByRole("region",{name:"阶段依据详情"}).scrollIntoViewIfNeeded();
  await expect(detail.getByRole("region",{name:"阶段依据详情"})).toBeInViewport();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:test.info().outputPath("stage-proposal-narrow.png")});
});
