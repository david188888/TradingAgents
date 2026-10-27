/** Credential-free official subscription configuration in the built workbench. */
import {test, expect} from "@playwright/test";

const accountRef = "cg_" + "a".repeat(32);
test("dynamic subscription selectors preserve removed choices and freeze account on submit", async ({page}) => {
  let models = [{id:"future-z",label:"Future Z"},{id:"future-mini",label:"Future Mini"}];
  let captured: Record<string, unknown> | null = null;
  await page.route("**/api/config", async route => {
    const original = await route.fetch();
    const config = await original.json();
    config.providers = config.providers.filter((p: {id:string})=>p.id!=="chatgpt");
    config.providers.push({id:"chatgpt",configured:false,authentication:"oauth",requires_api_key:false,custom_model_allowed:false,models:{quick:[],deep:[]}});
    await route.fulfill({json:config});
  });
  await page.route("**/api/chatgpt/**", async route => {
    const path = new URL(route.request().url()).pathname;
    await route.fulfill({json:path.endsWith("/models") ? {account_ref:accountRef, models, fetched_at:Date.now()/1000} : {
      accounts:[{account_ref:accountRef,label:"Demo Account",signed_in:true,plan_enabled:true,usage_paused:false,revocation_unconfirmed:false}],active_account_ref:accountRef,usage_url:"https://chatgpt.com/settings/usage"}});
  });
  await page.route("**/api/runs", async route => {
    if (route.request().method() !== "POST") {await route.continue(); return;}
    captured = route.request().postDataJSON();
    await route.fulfill({status:422,json:{detail:{code:"fixture_only",message:"Fixture request captured"}}});
  });
  await page.goto("/");
  await page.getByLabel("LLM Provider", {exact:true}).selectOption("chatgpt");
  await expect(page.getByLabel("专项与挑战模型", {exact:true})).toHaveValue("future-z");
  await page.getByLabel("综合模型", {exact:true}).selectOption("future-mini");
  await page.getByLabel("股票代码", {exact:true}).fill("600803");
  await expect(page.getByLabel("分析日期")).toHaveCount(0);
  await expect(page.getByRole("button", {name:"开始分析",exact:true})).toBeEnabled();
  models = [{id:"future-z",label:"Future Z"}];
  await page.getByRole("button", {name:"刷新模型",exact:true}).click();
  await expect(page.getByLabel("综合模型", {exact:true})).toHaveValue("future-mini");
  await expect(page.getByRole("button", {name:"开始分析",exact:true})).toBeDisabled();
  await expect(page.getByText("所选模型当前不可用，请刷新模型并重新选择", {exact:true})).toBeVisible();
  await page.getByLabel("综合模型", {exact:true}).selectOption("future-z");
  await page.getByRole("button", {name:"开始分析",exact:true}).click();
  await expect.poll(()=>captured).toMatchObject({llm_provider:"chatgpt",chatgpt_account_ref:accountRef,quick_think_llm:"future-z",deep_think_llm:"future-z"});
  await expect(page.locator("body")).not.toContainText("access_token");
});

test("unauthorized subscription requires explicit sign-in and blocks research", async ({page}) => {
 await page.route("**/api/chatgpt/status", route=>route.fulfill({json:{accounts:[],active_account_ref:null,usage_url:"https://chatgpt.com/settings/usage"}}));
 await page.goto("/");
 await page.getByLabel("LLM Provider", {exact:true}).selectOption("chatgpt");
 await expect(page.getByRole("button", {name:"Continue with ChatGPT",exact:true})).toBeVisible();
 await expect(page.getByRole("button", {name:"开始分析",exact:true})).toBeDisabled();
});

async function subscriptionConfig(page: import("@playwright/test").Page) {
 await page.route("**/api/config", async route => {
  const original = await route.fetch();
  const config = await original.json();
  config.defaults.llm_provider = "chatgpt";
  config.defaults.quick_think_llm = "";
  config.defaults.deep_think_llm = "";
  await route.fulfill({json:config});
 });
}
const readyAccount = {account_ref:accountRef,label:"long-private-account-label@privaterelay.appleid.example · fixture",signed_in:true,plan_enabled:true,usage_paused:false,revocation_unconfirmed:false};
const accountStatus = () => ({accounts:[readyAccount],active_account_ref:accountRef,usage_url:"https://chatgpt.com/settings/usage"});

test("first entry recovers a transient model failure without refreshing or reselecting", async ({page}) => {
 await subscriptionConfig(page);
 let modelCalls = 0;
 await page.route("**/api/chatgpt/**", async route => {
  if (new URL(route.request().url()).pathname.endsWith("/models")) {
   modelCalls++;
   if (modelCalls === 1) {await route.fulfill({status:503,json:{detail:{code:"request_failed",message:"临时连接失败"}}}); return;}
   await route.fulfill({json:{account_ref:accountRef,models:[{id:"first-model",label:"First model"}],fetched_at:1}});
  } else await route.fulfill({json:accountStatus()});
 });
 await page.goto("/");
 await expect(page.getByLabel("专项与挑战模型",{exact:true})).toHaveValue("first-model");
 await expect(page.getByText("模型已就绪",{exact:true})).toBeVisible();
 expect(modelCalls).toBe(2);
 await page.getByLabel("股票代码",{exact:true}).fill("600803");
 await expect(page.getByRole("button",{name:"开始分析",exact:true})).toBeEnabled();
 await page.getByRole("button",{name:"批量分析",exact:true}).click();
 await expect(page.getByLabel("综合模型",{exact:true})).toHaveValue("first-model");
});

test("reauthentication is explicit, reloads the same account and shows one actionable error", async ({page}) => {
 await subscriptionConfig(page);
 let connected = false;
 let loginBody: unknown;
 await page.route("**/api/chatgpt/**", async route => {
  const path = new URL(route.request().url()).pathname;
  if (path.endsWith("/models")) {
   if (!connected) {await route.fulfill({status:401,json:{detail:{code:"authorization_rejected",message:"ChatGPT 登录已失效，请重新认证。",diagnostic:{action:"sign_in"}}}}); return;}
   await route.fulfill({json:{account_ref:accountRef,models:[{id:"restored-model",label:"Restored model"}],fetched_at:1}});
  } else if (path.endsWith("/login")) {
   loginBody=route.request().postDataJSON();
   await route.fulfill({json:{attempt_id:"fixture-login",authorization_url:"https://auth.openai.com/api/accounts/authorize?fixture=true"}});
  } else if (path.endsWith("/login/fixture-login")) {
   connected=true;
   await route.fulfill({json:{status:"complete",account_ref:accountRef}});
  } else await route.fulfill({json:accountStatus()});
 });
 // No external login is performed in this fixture; test the popup-blocked path.
 await page.addInitScript(() => {window.open=()=>null;});
 await page.goto("/");
 await expect(page.getByText("ChatGPT 登录已失效，请重新认证。",{exact:true})).toHaveCount(1);
 await expect(page.getByText("需要重新认证",{exact:true})).toBeVisible();
 await expect(page.getByRole("button",{name:"开始分析",exact:true})).toBeDisabled();
 await expect(page.getByLabel("综合模型",{exact:true})).toContainText("模型暂不可用");
 await page.getByRole("button",{name:"重新认证",exact:true}).click();
 await expect(page.getByLabel("综合模型",{exact:true})).toHaveValue("restored-model");
 expect(loginBody).toEqual({account_ref:accountRef});
 await expect(page.getByText("模型已就绪",{exact:true})).toBeVisible();
 await expect(page.getByText("ChatGPT 登录已失效，请重新认证。",{exact:true})).toHaveCount(0);
});

test("sidebar fits desktop and narrow screens with long account labels", async ({page}) => {
 await subscriptionConfig(page);
 await page.route("**/api/chatgpt/**", async route => {
  await route.fulfill({json:new URL(route.request().url()).pathname.endsWith("/models")
   ? {account_ref:accountRef,models:[{id:"gpt-fixture",label:"GPT fixture"}],fetched_at:1} : accountStatus()});
 });
 await page.setViewportSize({width:1440,height:1000});
 await page.goto("/");
 await expect(page.getByText("模型已就绪",{exact:true})).toBeVisible();
 await expect(page.getByRole("heading",{name:"研究输入",exact:true})).toBeVisible();
 await expect(page.getByRole("heading",{name:"模型与账户",exact:true})).toBeVisible();
 await expect(page.getByRole("heading",{name:"历史记录",exact:true})).toBeVisible();
 await page.screenshot({path:"/tmp/tradingagents-sidebar-desktop.png",fullPage:true});
 for (const width of [320,390,768]) {
  await page.setViewportSize({width,height:1000});
  await expect(page.locator(".sidebar")).toBeVisible();
  expect(await page.locator(".sidebar").evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
 }
 await page.setViewportSize({width:390,height:1000});
 await page.screenshot({path:"/tmp/tradingagents-sidebar-narrow.png",fullPage:true});
});
