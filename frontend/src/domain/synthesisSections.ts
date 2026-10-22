import type { ResearchRecordV1DTO } from "../api/contracts";
import { dimensionLabel } from "./readerExplanation";

export function unfinishedSynthesis(record: ResearchRecordV1DTO): Set<string> {
  const a = record.assessment;
  return new Set(a?.schema_version === "research-assessment-v3"
    ? a.synthesis_sections?.sections.filter(s => s.status === "unavailable").map(s => s.section_id) : []);
}

export function synthesisSectionLabel(id: string, record: ResearchRecordV1DTO): string {
  if (id.startsWith("dimension:")) return dimensionLabel(id.slice("dimension:".length), true);
  if (id.startsWith("adjudication:")) {
    const index = record.challenges.findIndex(c => c.challenge_id === id.slice("adjudication:".length));
    return `挑战裁决 ${index + 1}`;
  }
  return id === "overall" ? "总体判断" : "改变判断的条件";
}
