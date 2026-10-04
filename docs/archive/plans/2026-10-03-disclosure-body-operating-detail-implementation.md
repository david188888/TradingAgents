# 公告正文与经营明细实施

Status: Archived Plan

Do not use this document as evidence of current implementation behavior.

归档日期：2026-10-04。正文保留编写时的设计、结果和未完成事项；归档不表示全部目标已验收。当前行为与仍待推进的计划见[文档索引](../../README.md)。

> 编写时状态：Archived Plan

Do not use this document as evidence of current implementation behavior.

已批准设计：[正文与经营披露](../designs/2026-10-03-disclosure-body-operating-detail-design.md)。

1. 新增确定性 PDF 提取器，PDF/发行人/期间校验；最多 20 MiB、500 页。
   经营表支持披露的收入构成五列与收入/成本/毛利六列表，跨页继承表头，
   金额使用 Decimal；披露毛利率允差为最后一位的一半加数值舍入容差。
2. 新 collector 子类：保留 v2 原 collector；v3 才选择报告和事件正文。
   日期倒序、公告 ID 字典序打破平局，报告优先正式全文，至多 1+3 文档。
   保存选择结果和每个安全失败代码，所有 HTTP/逻辑来源请求沿用 durable 额度。
3. 显式来源族与正文/经营行事实；三模式使用相同冻结来源，C1 仍只认旧封闭集合。
4. v3 核心上下文添加全局覆盖和专项范围，保存带 role 的 unknown；v1/v2
   的上下文与提示保持原语义以支持中断恢复。修复新版本可用维度的缺失标签。
5. Reader/Markdown 显示全局覆盖、缺口和专项待查，保留旧未知项的范围未知标签。
6. 离线解析/取数/恢复/三模式/渲染回归；重用两份公开 PDF 有限探测。
   运行 docs、Ruff、Python scoped、Vitest、typecheck/build、diff checks；
   同步 current docs、静态资源与独立验收记录。

没有 writing-plans 技能安装在本会话可用路径；该执行清单直接落实已批准设计。
