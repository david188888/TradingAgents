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
  await page.getByLabel("分析日期", {exact:true}).fill("2026-10-10");
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
