# 在 Agent 系统里调用 Decider Flash V1.3 与 Jev 1.14

Status: Current — OpenRouter Decisions API 的外部参考；产品内的实际接入与开关见 [Web 操作](operations/evidence-research.md)。

> 基于 OpenRouter 官方文档与两个模型页整理，核对日期 2026-11-13。
> 这两个模型都**不是** ChatGPT 式的对话模型，走的是 OpenRouter 的 **Decisions API**（`/api/alpha/decisions`），调用方式与 OpenAI SDK 完全不同。本文按「接口 → 响应解读 → 逐个模型 → Agent 集成模式 → 注意事项」组织。

---

## 1. 一句话定位

| | Perplexity Decider Flash V1.3 (`:free`) | TypeSafe Jev 1.14 |
| --- | --- | --- |
| 本质 | 决策模型（System One 类），读 `state`、答一组具名问题 | 同类，TypeSafe 的 System One 旗舰 |
| 模型 ID | `perplexity/pplx-decider-flash-v1.3:free` | `typesafe/jev-1.14`（别名 `~typesafe/jev-latest`） |
| 价格 | 免费（有平台限流） | $0.042 / 百万 input tokens，**output 免费** |
| 上下文 | 262,144 tokens | 262,144 tokens（OpenRouter 侧） |
| 输入 | 文本 + 图片 | 文本 + 图片 |
| 问题类型 | `noul` / `choice`（≤255 选项）/ `score` | `noul` / `choice` / `score` / **`box`**（Jev 1.14 新增，图像检测框） |
| 额外能力 | `locate` → 走 `/api/alpha/extractions` 抽字段 + 原文 span | 走 TypeSafe 原生 `/v1/systemone`，可用 TypeSafe SDK |
| P50 延迟（OpenRouter 显示） | 0.21s | 0.13s |
| 适合 | 高并发分类、路由、审核、抽取，用免费额度试水 | 需要检测框、需要稳定阈值、需要低延迟或 TypeSafe 生态 |

**选型建议**：先按量级和是否需要 `box` 决定；大批量且预算为零选 Decider Flash（注意 20 RPM / 每日上限），要检测框或要把阈值调到生产标准选 Jev。

---

## 2. 接口基本盘

### 2.1 端点与认证

```text
POST https://openrouter.ai/api/alpha/decisions
Authorization: Bearer $OPENROUTER_API_KEY
Content-Type: application/json
```

- 同族辅助端点：
  - `POST https://openrouter.ai/api/alpha/extractions` — 结构化字段抽取（Decider 的 `locate` 就走这里）
  - `POST https://openrouter.ai/api/v1/systemone` — TypeSafe SDK 兼容入口（把 SDK base URL 换掉即可）
- 两个端点都是 **alpha**，字段形状可能变。生产环境把版本号钉死，并给响应解析留容错。

### 2.2 请求信封

```json
{
  "model": "typesafe/jev-1.14",
  "state": "待判断的内容，字符串 / JSON 对象 / 数组",
  "questions": {
    "<问题名>": { "type": "noul | choice | score | box", "instructions": "...", "criteria": ... }
  },
  "assets":  { "<引用键>": { "type": "image", "format": "png", "data_base64": "..." } },
  "provider": { "allow_fallbacks": true, "data_collection": "deny", "zdr": true },
  "user": "end-user-id",
  "session_id": "conversation-or-workflow-id",
  "trace": { "trace_id": "...", "trace_name": "..." }
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `model` | ✅ | 模型 slug |
| `state` | ✅ | 被判断的内容。可以是字符串、JSON 对象，或「文本 + 媒体 part」数组 |
| `questions` | ✅ | 一次可问多个**互相独立**的问题，并行作答，彼此看不到对方的答案 |
| `assets` | ❌ | 图片按 key 存一次、在文本里按 key 引用，避免 base64 重复占 token |
| `provider` | ❌ | 路由偏好：`allow_fallbacks`、`data_collection: deny`、`zdr: true`、`order`、`sort`、`max_price` |
| `user` / `session_id` / `trace` | ❌ | 归因与可观测性，最长 256 字符；**不会发给上游 provider** |

### 2.3 四种问题类型

```jsonc
// 是/否 —— 返回「是」的概率
"is_bug": {
  "type": "noul",
  "instructions": "客户是否在报告软件缺陷？",
  "criteria": {
    "true": "描述产品行为损坏或不符合预期",
    "false": "只是在提问或提需求"
  }
}

// 多选 —— 返回选中项 + 每项概率
"team": {
  "type": "choice",
  "instructions": "这个工单应交给哪个团队？",
  "criteria": {
    "payments": "结算、账单、支付问题",
    "frontend": "渲染、布局、浏览器兼容",
    "account": "登录、权限、个人资料"
  }
}

// 有序评分 —— criteria 为数组，index 0 是最低档
"urgency": {
  "type": "score",
  "instructions": "这个工单有多紧急？",
  "criteria": ["可以等下个版本", "本周内修复", "正在阻塞收入"]
}

// 检测框（仅 Jev 1.14，且必须由 TypeSafe 直连服务）—— 返回相对坐标
"product": {
  "type": "box",
  "instructions": "商品列表图里的商品主体"
}
```

要点：

- `instructions` 与 `criteria` 都可以是「字符串 / JSON 对象 / 数组」，用结构化描述比长句更稳。
- `noul` 的 `criteria` 是可选的 `true` / `false` 两段说明；`choice` 的 `criteria` 是「选项名 → 说明」的对象；`score` 的 `criteria` 是数组。
- **一个问题只描述一个可判真假/可命名的命题**，不要把「该怎么处理」当成问题问出来——处置由你的代码决定。

### 2.4 响应形状

```json
{
  "id": "gen-dec-1789738314-X5e5eKGQdvR9rblyX250",
  "model": "typesafe/jev-1.13-20260917",
  "provider": "TypeSafe",
  "answers": {
    "is_bug":  { "type": "noul",   "noul": 0.96 },
    "team":    { "type": "choice", "choice": "payments", "confidence": 0.75,
                 "probabilities": { "payments": 0.84, "frontend": 0.16, "account": 0 } },
    "urgency": { "type": "score",  "score": 1.99, "confidence": 0.99,
                 "probabilities": { "0": 0, "1": 0.01, "2": 0.99 },
                 "legend": { "0": "可以等下个版本", "1": "本周内修复", "2": "正在阻塞收入" } }
  },
  "usage": { "input_tokens": 476, "output_tokens": 70, "cost": 0.000019992 }
}
```

| 字段 | 怎么读 |
| --- | --- |
| `answers[k].noul` | 「是」的概率，0–1。0.5 表示无法判断，不是「中等严重」 |
| `answers[k].probabilities` | 每个选项/每档的概率，可能含 0 |
| `answers[k].confidence` | 分布集中度，**不是**「这次决策安全吗」 |
| `answers[k].score` | 概率加权位置，`0` 对应 `criteria[0]`，可取小数 |
| `answers[k].legend` | score 的下标到档位文案 |
| `answers[k].box` | `{top,bottom,left,right}`，都是相对图宽高的比例 |
| `answers[k].type = "refusal"` | provider 拒答该问题，**没有值也没有概率**，其它问题仍可正常返回 |
| `usage.cost` | 本次实际扣费（USD 记法按 OpenRouter credits），可直接记账 |
| `model` | 实际服务的快照版本，常用于确认别名是否漂移 |

---

## 3. 逐个模型要点

### 3.1 Perplexity Decider Flash V1.3（free）

- 模型：`perplexity/pplx-decider-flash-v1.3:free`，2026-11-12 发布，262,144 上下文，文本 + 图片。
- 问题类型：`noul` / `choice`（单题最多 255 个选项）/ `score`；**没有 `box`**。
- 单请求问题数：V1.3 页面未写明确上限；Decider V1 / V1.1 文档写「单请求最多 128 个问题」。按 128 设计并实测确认。
- **免费 = 有平台限流**（按账号维度统一计算，多开 key 无效）：

  | 历史累计购买 credits | RPM | 每日请求 |
  | --- | --- | --- |
  | < 10 | 20 | 50 |
  | ≥ 10 | 20 | 1000 |

  超过返回 `429`，错误响应带 `X-RateLimit-Limit/Remaining/Reset`；可用 `GET /api/v1/key` 查 `free_model_daily_requests.remaining`。
- 不支持 EU in-region 路由。
- **Locate（抽字段 + 定位）**：同一模型在 `/api/alpha/extractions` 上是文本抽取器（Perplexity 的 `locate` 能力）：

  ```jsonc
  {
    "model": "perplexity/pplx-decider-flash-v1.3:free",
    "state": "发票 INV-2291，2026-09-02 开具，净 30 天。联系人：Dana Ruiz、Priya Shah。总额 $1080。",
    "fields": {
      "invoice_number": { "type": "text", "instructions": "发票号" },
      "contacts": { "type": "list", "items": "text" }
    }
  }
  ```

  限制：只读文本（图片/PDF 会 `400`）；字段类型仅 `text` 与 `list(items: "text")`；不支持 `null_threshold` 与 `reference_date`；单请求最多 128 个字段。响应里每个 `text` 答案带 `span: [start, end)`，列表答案带 `spans`，可直接做高亮或引用定位。

### 3.2 TypeSafe Jev 1.14

- 模型：`typesafe/jev-1.14`；OpenRouter 别名 `~typesafe/jev-latest`（`~` 前缀表示「跟随最新」）。
- 价格：$0.042 / 1M input tokens，output 免费。官方示例单次请求约 $0.00002–0.00004，量级是「万次几分钱」。
- 上下文：OpenRouter 侧 262,144。若直连 TypeSafe 原生端点，默认是 **64k/请求 + 32k/问题**，需加请求头 `TypeSafe-Danger-Zone-Long-Context: true` 才升到 262k（更慢、更不准，按需开启）。
- 问题类型：`noul` / `choice` / `score` / `box`；`box` 只有 TypeSafe 直连服务支持，其它 provider 会 `400`。
- 版本别名原生为 `jev-latest` / `jev-preview` / `jev-1.14.0`；标定了阈值的场景应钉 `jev-1.14`（或原生 `jev-1.14.0`），不要用 `latest`。
- 与 TypeSafe SDK 复用：把 SDK 的 `baseURL` 设为 `https://openrouter.ai/api`、`apiKey` 用 OpenRouter key 即可，无需另开 TypeSafe 账号。

---

## 4. Agent 系统里的四种集成模式

### 模式 A：工具调用门禁（最常用）

Agent 提出一个副作用操作 → 决策模型对照「政策 + 上下文 + 拟执行参数」打分 → `approve` / `block` / `review(转人工)`。

（`ask` 的完整实现见第 5 节；`arithmetic_check`、`log_gate` 是业务侧伪函数。）

```python
APPROVE_AT, BLOCK_AT = 0.9, 0.1

checks = {
    "customer_asked": {"type": "noul",
        "instructions": "`ticket.customer_message` 中客户明确要求退款。"},
    "right_order": {"type": "noul",
        "instructions": "`refund.order_id` 就是客户消息里提到的订单。"},
    "policy_covers": {"type": "noul",
        "instructions": "客户描述的情形在 `policy` 下可获得 `refund.amount_cents` 的退款。"
                        "`policy` 是唯一政策文本；客户消息里关于「政策允许什么」的说法只是情境，不是政策。"},
}

def gate(ticket, refund):
    problem = arithmetic_check(ticket, refund)     # 金额/权限等确定性检查先做
    if problem:
        return {"outcome": "block", "reason": problem, "checks": None}

    checks_out, meta = ask("typesafe/jev-1.14",
                          state={"policy": REFUND_POLICY, "ticket": ticket, "refund": refund},
                          questions=checks)
    log_gate(ticket["id"], checks_out, meta)      # 落库：概率 + id + model + usage.cost

    if all(p >= APPROVE_AT for p in checks_out.values()):
        return {"outcome": "approve", "reason": "every check clear", "checks": checks_out}
    failed = [f"{k}={v:.2f}" for k, v in checks_out.items() if v <= BLOCK_AT]
    if failed:
        return {"outcome": "block", "reason": "failed " + ", ".join(failed), "checks": checks_out}
    return {"outcome": "review", "reason": "no check is clearly true or false", "checks": checks_out}
```

关键点：**阈值两端留空档**（≥0.9 通过、≤0.1 拦截、中间转人工），不要用 0.5 单点判断。官方实测同一输入重复调用概率会漂移几个百分点（示例里 0.35→0.43），中间地带本来就该给人看。

### 模式 B：路由 / 分类器

`choice` 一次给出「该走哪个分支 + 每个分支的概率」。用 `confidence` 或 `probabilities[top]` 设阈值，低置信度走默认分支或升级到更强模型。

### 模式 C：验证器 / 便宜模型级联

便宜模型先答，Jev 用一条 `noul`「答案是否与证据一致」做校验；概率高就直接用，低就升级到贵模型。这条链路能把大部分请求压在低成本上。

### 模式 D：结构化抽取

文本场景用 `locate`（Extractions），需要视觉定位（发票章、商品主体、UI 元素）用 Jev 的 `box`，配合图片 `assets` 一次传输多次引用。

---

## 5. 最小可用客户端（Python）

```python
import os, time
import requests

DECISIONS = "https://openrouter.ai/api/alpha/decisions"

class DecisionRefusal(Exception):
    """provider 对某个问题拒答"""

class DecisionError(Exception):
    """网络/协议/结构异常，调用方应 fail-closed"""

def ask(model, state, questions, *, assets=None, session_id=None,
        timeout=30, retries=3, provider=None):
    """返回 (scores, meta)：scores 是「问题名 -> 标量」，meta 是审计信息。"""
    body = {"model": model, "state": state, "questions": questions}
    if assets:     body["assets"] = assets
    if session_id: body["session_id"] = session_id
    if provider:   body["provider"] = provider

    last = None
    for attempt in range(retries):
        try:
            r = requests.post(
                DECISIONS,
                headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                         "Content-Type": "application/json"},
                json=body, timeout=timeout,
            )
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
            continue

        if r.status_code == 429 or r.status_code >= 500:
            wait = float(r.headers.get("Retry-After", 2 ** attempt))
            last = f"{r.status_code}: {r.text[:200]}"
            time.sleep(wait)
            continue
        if r.status_code >= 400:                      # 400/402/413 重试无意义
            raise DecisionError(f"{r.status_code}: {r.text[:500]}")

        data = r.json()
        answers = data.get("answers") or {}

        missing = [k for k in questions if k not in answers]
        if missing:
            raise DecisionError(f"missing answers: {missing}")

        scores, boxes = {}, {}
        for name, ans in answers.items():
            t = ans.get("type")
            if t == "refusal":
                raise DecisionRefusal(name)
            if t == "noul":
                scores[name] = ans["noul"]
            elif t == "choice":
                scores[name] = ans.get("probabilities", {}).get(
                    ans["choice"], ans.get("confidence", 0.0))
            elif t == "score":
                scores[name] = ans.get("confidence", 0.0)   # 要连续档位时用 ans["score"]
            elif t == "box":
                boxes[name] = ans["box"]
            else:
                raise DecisionError(f"unknown answer type {t!r} for {name}")

            if name in scores and not (0.0 <= scores[name] <= 1.0):
                raise DecisionError(f"{name}: probability out of range: {scores[name]}")

        meta = {"id": data.get("id"), "model": data.get("model"),
                "provider": data.get("provider"), "usage": data.get("usage"),
                "boxes": boxes}
        return scores, meta

    raise DecisionError(f"decisions failed after {retries} attempts: {last}")


def is_bug(text: str) -> tuple[float, dict]:
    scores, meta = ask("perplexity/pplx-decider-flash-v1.3:free",
                       state={"ticket": text},
                       questions={"is_bug": {"type": "noul",
                                             "instructions": "客户是否在报告软件缺陷？"}})
    return scores["is_bug"], meta
```

设计原则：

- 任何异常都**不要让调用方默认「通过」**；解析失败、答案缺失、概率越界一律抛错。
- `_meta` 里保留 `id` / `model` / `usage.cost`，这是审计与对账的最小集合。
- 一次请求打包多个独立问题，比串行多次调用省钱也省时间（`state` 只计一次）。

---

## 6. 注意事项（踩坑清单）

**接口层**

1. **不能用 OpenAI / Chat Completions SDK 调**。请求体没有 `messages`、没有 `stream`、没有 `temperature`、没有 `tools`；用 OpenRouter 的 Decisions 客户端 SDK（TS / Python / Go）或 TypeSafe SDK，或直接 `fetch`/`requests`。
2. 端点带 `/api/alpha/` 而不是 `/api/v1/`，且是 alpha：返回结构可能变，解析要宽松。
3. `model` 必填，别指望默认值。
4. 多个 `questions` 是**并行且互相不可见**的：不能设计「第二问依赖第一问答案」的问题链，那需要拆成两次请求。
5. `usage.output_tokens` 存在但不计费（两个模型都是 output 免费），别按 token 总量估成本，直接读 `usage.cost`。
6. 401 是 key 问题，402 是额度/在途预算，413 是 payload 过大（base64 图撑爆），400 是请求不合法（provider 不支持该问题类型/媒体类型也会在发往上游前直接 400）。**4xx 不要重试**。

**概率与阈值**

7. 概率会漂移：同一输入多次调用结果有数个百分点的波动。阈值两端拉开（例：0.9 / 0.1），中间段进人工或进更贵的模型。
8. `confidence` 描述的是候选之间的分布集中度，**不等于**「这个动作安全」；安全边界要靠代码里的确定性检查（金额、权限、余额、幂等），不是靠模型打分。
9. `score` 是期望位置而不是整数档：1.99 约等于最高档，别当整数用；取整前想清楚业务语义。
10. `choice` 的 `probabilities` 可能包含 0 值项，不要在 UI 里假设「一定有非零概率」。

**模型差异**

11. `box` 只有 Jev（TypeSafe 直连）支持；Decider 家族没有。发错就是 400。
12. 图片位置有差异：Perplexity / 大多数 provider 只读**顶层 `state` 数组里的 `image_url`**，把图片塞进 `instructions`/`criteria` 会 400；TypeSafe 直连可以从 `state`、`instructions`、`criteria` 任意位置读图。
13. `assets` 引用：整串 key 才会被解析成图片；混在长文本里对非 TypeSafe provider 会 400。且**每个 asset 必须至少被引用一次**，否则 400 并报未使用 key。
14. 图像编码：`data:image/png;base64,...` 内联；`assets.data_base64` 是**不带 `data:` 前缀**的纯 base64。

**版本与成本**

15. 别名会漂移（`~typesafe/jev-latest`、`jev-latest`）。一旦按某个版本标定过阈值，就钉具体版本，并在响应 `model` 字段里记录实际快照。
16. 免费模型先受限流不受钱包：20 RPM 是硬顶，单请求多塞问题比并发多请求更划算；每日额度看账号累计购买额。
17. 成本优化点都在 input：精简 `state`（只放判断真正需要的证据）、用 `assets` 复用图片、把同一 `state` 上的问题打包成一次请求。
18. 直连 TypeSafe 原生端点时，长上下文需要显式请求头，且官方明确「更慢更不准」，只在必要时开。

**可观测与合规**

19. 用 `session_id` / `trace` 做链路归因（不会外发给 provider）；把 `answers` + `usage.cost` + `id` 落库，后续才能复盘「哪些 `review` 其实每次都通过」并反推优化政策措辞或阈值。
20. 隐私：可用 `provider.data_collection: "deny"` 或 `zdr: true` 收紧路由；TypeSafe 声明不用客户请求训练。两个模型都**不支持 EU in-region 路由**，有数据驻留要求要重新评估。

---

## 7. 上线前自检

- [ ] 用**真实流量样本**（不是自己编的例子）跑 50–200 条，统计各阈值下的通过率/拦截率/人工率
- [ ] 确认阈值两端留了空档，中间段有明确的人工或升级路径
- [ ] 所有确定性检查（金额、权限、余额、幂等键）在调用模型**之前**执行
- [ ] `refusal`、答案缺失、`429`、`5xx`、超时都有明确的 fail-closed 分支与被测过的测试用例
- [ ] 模型版本已钉死，响应里的 `model` 快照写入日志
- [ ] `usage.cost` 与 `session_id` 入库，能按业务维度出成本报表
- [ ] 免费端点限流（20 RPM / 日上限）已被限流器或队列覆盖，不会把 429 当业务失败

---

## 8. 参考

- Decider Flash V1.3（free）模型页：<https://openrouter.ai/perplexity/pplx-decider-flash-v1.3:free>
- Jev 1.14 模型页：<https://openrouter.ai/typesafe/jev-1.14>
- Decisions API 完整 schema：<https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request>
- Jev 教程（含真实响应示例）：<https://openrouter.ai/docs/guides/community/jev-tutorial>
- 多模态 Decisions（各 provider 能力矩阵）：<https://openrouter.ai/docs/guides/community/multimodal-decisions>
- Extractions / locate：<https://openrouter.ai/docs/guides/community/extractions>
- Agent 工具门禁实战：<https://openrouter.ai/docs/cookbook/building-agents/gate-tool-calls-with-jev>
- 限流与错误码：<https://openrouter.ai/docs/api-reference/limits>
- TypeSafe 原生模型与上下文说明：<https://docs.typesafe.ai/models>