export type Workflow = 'read' | 'create' | 'update' | 'all';
export type Condition = 'source_only' | 'runtime_only' | 'hybrid';
export type Job = { id: string; kind: string; state: string; message: string; progress: number;
  created_at: string; result: unknown; };
export type Attempt = { attempt: number; evaluation_status: string; passed_count: number;
  scenario_count: number; provenance: { provider: string; model: string; latency_seconds: number };
  source_assembly?: { version: string; model_first_line: number };
  repair_rollback?: { reason: string; next_repair_base_sha256: string; raw_draft_preserved: boolean }; };
export type Run = { run_id: string; workflow: Workflow; condition: Condition; status: string;
  max_repairs?: number;
  stop_reason?: string;
  call_ledger?: { call_limit: number; remaining: number; reserved_requests: number; legacy_requests_consumed: number };
  held_out_report_sha256?: string;
  held_out_status?: string;
  provider_policy?: string; attempts: Attempt[]; failure?: { category: string; retryable?: boolean;
  attempt?: number; local_rebuild_available?: boolean;
  attempts?: { provider: string; category?: string; http_status?: number }[] }; };
export type Mismatch = { path: string; expected: unknown; actual: unknown; reason: string };
export type Report = { status: string; passed_count: number; scenario_count: number;
  source_sha256: string; results: { scenario_id: string; passed: boolean; mismatches: Mismatch[] }[] };
export type RunDetail = { result: Run | null; source: string | null; guidance: Report[];
  generation_settings?: { staged_read: boolean; groq_reasoning_effort: 'low' | 'medium' | 'high' | null };
  held_out: Report | null; approval: { source_sha256: string; verification_sha256: string;
  reviewer: string; notes: string } | null };
export type Evidence = { method_count: number; source_file_count: number; parse_error_files: string[];
  unknowns: string[]; sources: { evidence_id: string; path: string; start_line: number;
  end_line: number; text: string; symbol: string; retrieval_score: number }[];
  rails_inferences: { path: string; line: number; convention: string; text: string }[] };
export type Health = { status: string; project: string; prepared: boolean; source_commit: string;
  synthetic_fixture?: boolean;
  execution: string; contract: { version: string; guidance_count: number; held_out_count: number };
  providers: Record<string, { configured: boolean; model: string }> };

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-LegacyLift-Client': 'workbench' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    try { throw new Error(JSON.parse(text).detail ?? text); }
    catch (error) { if (error instanceof SyntaxError) throw new Error(text); throw error; }
  }
  return response.json() as Promise<T>;
}
