import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import oldFixture from '../../test/fixtures/unified-research-v7.json';
import fixture from '../../test/fixtures/dual-search-research-v8.json';
import type { ResearchRecordV1DTO, ResearchRecordV2DTO } from '../../api/contracts';
import { SearchResearch } from './SearchResearch';

const record = () => structuredClone(fixture) as ResearchRecordV2DTO;

describe('search research history', () => {
  it('leaves the legacy record display unchanged', () => {
    const { container } = render(<SearchResearch record={oldFixture as ResearchRecordV1DTO}/>);
    expect(container).toBeEmptyDOMElement();
  });
  it('shows three rounds, their evidence versions and retained questions', () => {
    render(<SearchResearch record={record()}/>);
    expect(screen.getByRole('heading', { name: '联网补证与专项复核' })).toBeInTheDocument();
    for (const n of [1, 2, 3]) expect(screen.getAllByText(`第 ${n} 轮补证`).length).toBeGreaterThan(0);
    expect(screen.getByText(/已达到三轮补搜上限/)).toBeInTheDocument();
    expect(screen.getByText('证据版本与适用范围')).toBeInTheDocument();
  });
  it('distinguishes provider degradation and search summaries', () => {
    const value = record();
    value.search_batches[0].outcomes[1] = {task_id:'missing', provider:'tavily', status:'unavailable', hits:[], reason:'not_configured', retryable:false, usage:null};
    value.search_batches[0].hits[0].content = '';
    value.search_batches[0].hits[0].summary = '仅供发现页面的搜索摘要';
    render(<SearchResearch record={value}/>);
    expect(screen.getByText(/单路降级/)).toBeInTheDocument();
    expect(screen.getByText(/仅搜索摘要，未作为原文入库/)).toBeInTheDocument();
  });
  it('does not claim new material has already been reviewed', () => {
    const value = record();
    value.search_reviews = [];
    render(<SearchResearch record={value}/>);
    expect(screen.getByText(/经营研究有新材料尚未完成复核/)).toBeInTheDocument();
  });
});

it('keeps a partially recovered field beside the remaining request', () => {
  const value = record();
  const source = value.evidence.find(s=>s.content)!;
  const demand = {ticker:value.ticker, field:'revenue', period:'2026-06-30', window_start:null,
    unit:'CNY', currency:'CNY', basis:'consolidated_actual'};
  value.search_batches[0].requests[0].requirements = [demand, {...demand, field:'n_cashflow_act'}];
  value.recovered_fields = [{...demand, value:'120.50', evidence_id:source.evidence_id,
    locator:'合并利润表营业收入', source_content_sha256:source.content!.content_sha256}];
  render(<SearchResearch record={value}/>);
  expect(screen.getByText('接口补缺：已恢复 1 个合格字段')).toBeInTheDocument();
  expect(screen.getByText(/仍未恢复的请求字段：经营现金流净额/)).toBeInTheDocument();
});
