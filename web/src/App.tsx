import { lazy, Suspense, useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, ArrowDownToLine, ArrowRight, Braces, Check, ChevronRight, Circle,
  Database, FileCode2, FlaskConical, GitBranch, Layers3, LoaderCircle, Play, ShieldCheck,
  Square, Terminal, Workflow as WorkflowIcon } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { api } from './api';
import type { Condition, Evidence, Health, Job, Report, Run, RunDetail, Workflow } from './api';

const CodeViewer = lazy(() => import('./CodeViewer'));

const activeStates = ['queued', 'running', 'cancelling'];
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const label = (value: string) => value.replaceAll('_', ' ');
const runStatus = (run: Run) => run.status !== 'passed' ? run.status :
  run.held_out_status === 'passed' ? 'verified' :
  run.held_out_status ? 'held-out failed' : 'guidance matched';
const statusClass = (status: string) => status === 'passed' || status === 'succeeded' ? 'good' :
  status === 'verified' ? 'good' : status.includes('fail') || status.includes('blocked') ? 'bad' : 'neutral';

function Status({ value }: { value: string }) {
  return <span className={`status ${statusClass(value)}`}><i />{label(value)}</span>;
}

function Results({ report, title }: { report: Report | null | undefined; title: string }) {
  const [open, setOpen] = useState('');
  if (!report) return <div className="empty compact"><FlaskConical size={25}/><b>{title} pending</b>
    <span>Results appear after independent container verification.</span></div>;
  return <section className="result-block"><div className="section-heading"><h3>{title}</h3>
    <Status value={report.status}/></div>
    <p className="muted">{report.passed_count ?? 0} of {report.scenario_count ?? 0} scenarios match.</p>
    {(report.results ?? []).map(result => <div className="scenario" key={result.scenario_id}>
      <button className="scenario-toggle" onClick={() => setOpen(open === result.scenario_id ? '' : result.scenario_id)}>
        {result.passed ? <Check size={16} className="mint"/> : <Circle size={13} className="red"/>}
        <code>{result.scenario_id}</code><span>{result.passed ? 'Matched' : `${result.mismatches.length} differences`}</span>
        <ChevronRight size={14}/></button>
      {open === result.scenario_id && result.mismatches.map((difference, i) => <div className="difference" key={i}>
        <code>{difference.path}</code><div className="diff-columns"><div><small>LEGACY</small>
          <pre>{pretty(difference.expected)}</pre></div><div><small>CANDIDATE</small>
          <pre>{pretty(difference.actual)}</pre></div></div></div>)}
    </div>)}
  </section>;
}

export default function App() {
  const client = useQueryClient();
  const [tab, setTab] = useState<'evidence' | 'migration' | 'verification'>('evidence');
  const [workflow, setWorkflow] = useState<Workflow>('read');
  const [condition, setCondition] = useState<Condition>('hybrid');
  const [provider, setProvider] = useState('auto');
  const [stagedRead, setStagedRead] = useState(false);
  const [reasoning, setReasoning] = useState<'low' | 'medium' | 'high'>('medium');
  const [runId, setRunId] = useState('');
  const [sourceIndex, setSourceIndex] = useState(0);
  const [error, setError] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [notes, setNotes] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/health'), refetchInterval: 5000 });
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => api<Job[]>('/jobs'), refetchInterval: 2000 });
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => api<Run[]>('/runs'), refetchInterval: 3000 });
  const evidence = useQuery({ queryKey: ['evidence', workflow],
    queryFn: () => api<Evidence>(`/evidence?workflow=${workflow === 'all' ? 'read' : workflow}`),
    enabled: health.data?.prepared === true });
  const detail = useQuery({ queryKey: ['run', runId], queryFn: () => api<RunDetail>(`/runs/${runId}`),
    enabled: !!runId, refetchInterval: 3000 });
  const start = useMutation({ mutationFn: (body: unknown) => api<Job>('/jobs', body),
    onSuccess: () => { setError(''); void client.invalidateQueries({ queryKey: ['jobs'] }); },
    onError: (e: Error) => setError(e.message) });
  const approve = useMutation({ mutationFn: () => api(`/runs/${runId}/approve`, {
    reviewer, notes, source_sha256: detail.data?.held_out?.source_sha256,
    reviewed_source_and_limitations: reviewed,
  }), onSuccess: () => { setError(''); void client.invalidateQueries({ queryKey: ['run', runId] }); },
  onError: (e: Error) => setError(e.message) });
  const live = jobs.data?.find(job => activeStates.includes(job.state));
  const selected = evidence.data?.sources[sourceIndex] ?? evidence.data?.sources[0];
  const data = detail.data;
  const stagedEligible = workflow === 'read' && condition === 'hybrid' && ['groq', 'gemini'].includes(provider);
  const useStaged = stagedRead && stagedEligible;
  const budget = data?.result?.call_ledger;
  const exhausted = budget?.remaining === 0;
  useEffect(() => {
    setStagedRead(data?.generation_settings?.staged_read ?? false);
    setReasoning(data?.generation_settings?.groq_reasoning_effort ?? 'medium');
  }, [runId, data?.generation_settings?.staged_read, data?.generation_settings?.groq_reasoning_effort]);
  const latest = data?.guidance.at(-1);
  const chart = [{ name: 'Guidance', matched: latest?.passed_count ?? 0,
    different: (latest?.scenario_count ?? 0) - (latest?.passed_count ?? 0) },
    { name: 'Held out', matched: data?.held_out?.passed_count ?? 0,
      different: (data?.held_out?.scenario_count ?? 0) - (data?.held_out?.passed_count ?? 0) }];

  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="/"><span className="brand-icon"><Layers3 size={23}/></span>
      <span>LegacyLift<small>MIGRATION WORKBENCH</small></span></a>
      <div className="workspace-label">WORKSPACE <span>LOCAL</span></div>
      <div className="project-card"><div className="ruby-icon">Rb</div><div><b>Redmine</b>
        <small>4.2.10 · Ruby on Rails</small></div><GitBranch size={15}/></div>
      <div className="path-label"><ArrowRight size={14}/> Python 3.14 / FastAPI</div>
      <nav aria-label="Workbench"><button className={tab === 'evidence' ? 'selected' : ''} onClick={() => setTab('evidence')}>
        <GitBranch size={18}/> Evidence <span>01</span></button>
        <button className={tab === 'migration' ? 'selected' : ''} onClick={() => setTab('migration')}>
          <Braces size={18}/> Migration <span>02</span></button>
        <button className={tab === 'verification' ? 'selected' : ''} onClick={() => setTab('verification')}>
          <ShieldCheck size={18}/> Verification <span>03</span></button></nav>
      <div className="sidebar-note"><ShieldCheck size={19}/><b>Evidence before confidence</b>
        <p>Original code stays intact. Every candidate runs in its own restricted container.</p></div>
      <div className="sidebar-footer"><span className="dot"/>{health.data ? 'Controller connected' : 'Connecting…'}
        <small>{health.data?.execution ?? 'Local controller'}</small></div>
    </aside>
    <main><header className="topbar"><span>Projects <ChevronRight size={14}/> Redmine <ChevronRight size={14}/>
      <b>{tab[0].toUpperCase() + tab.slice(1)}</b></span><div><span className="outline-tag">GPL-2.0-or-later</span>
      <span className="avatar">LL</span></div></header>
      <div className="content">{health.data?.synthetic_fixture && <div className="synthetic-banner" role="status">
        <b>Synthetic test fixture</b><span>This isolated walkthrough is not a Redmine migration result or real verification.</span>
      </div>}<div className="page-heading"><div><p className="eyebrow">CROSS-LANGUAGE MODERNIZATION</p>
        <h1>{tab === 'evidence' ? 'Understand what must survive.' : tab === 'migration' ? 'Build from observed behavior.' : 'Prove the behavior matches.'}</h1>
        <p className="subtitle">{tab === 'evidence' ? 'Inspect the real legacy system before generating its replacement.' :
          tab === 'migration' ? 'Review every draft, its evidence, and the feedback that changed it.' :
          'Compare HTTP contracts and database effects against a frozen legacy oracle.'}</p></div>
        <div className="version">REFERENCE <b>Redmine 4.2.10</b><small>{health.data?.source_commit.slice(0, 9) ?? 'Pinned commit'}</small></div></div>
      {(error || health.error) && <div role="alert" className="error-banner">{error || health.error?.message}</div>}
      <div className="pipeline-strip"><div><span className={health.data?.prepared ? 'step ready' : 'step'}>{health.data?.prepared ? <Check size={15}/> : '1'}</span>
        Reference & fixtures</div><ArrowRight size={16}/><div><span className="step">2</span> Evidence-grounded draft</div>
        <ArrowRight size={16}/><div><span className="step">3</span> Independent verification</div><span className="strip-end">3 SELECTED WORKFLOWS</span></div>
      <div className="toolbar"><div className="segment"><label htmlFor="workflow">Workflow</label>
        <select id="workflow" value={workflow} onChange={e => { setWorkflow(e.target.value as Workflow); setSourceIndex(0); }}>
          <option value="read">Read & visibility</option><option value="create">Issue creation</option>
          <option value="update">Status & audit</option><option value="all">All selected workflows</option></select></div>
        <span className="toolbar-note"><Database size={15}/> Synthetic fixtures only</span>
        {!health.data?.prepared && <button className="primary" disabled={!!live || start.isPending} onClick={() => start.mutate({ kind: 'prepare' })}>
          <Play size={15}/> Prepare reference</button>}</div>
      {live && <section className="job-banner"><LoaderCircle size={20} className="spin"/><div><b>{label(live.kind)} in progress</b>
        <span>{live.message}</span><progress value={live.progress} max={1}/></div>
        <button className="ghost" onClick={() => { void api(`/jobs/${live.id}/cancel`, {}).then(() => client.invalidateQueries({ queryKey: ['jobs'] })).catch((e: Error) => setError(e.message)); }}>
          <Square size={13}/> Cancel</button></section>}

      {tab === 'evidence' && <><div className="stats"><div><FileCode2/><strong>{evidence.data?.method_count.toLocaleString() ?? '—'}</strong><span>Ruby methods indexed</span></div>
        <div><WorkflowIcon/><strong>3</strong><span>Selected workflow slices</span></div>
        <div><FlaskConical/><strong>{health.data?.contract.guidance_count ?? 18}<small> / {health.data?.contract.held_out_count ?? 12}</small></strong><span>Guidance / held-out scenarios</span></div>
        <div><GitBranch/><strong>{evidence.data?.parse_error_files.length ?? '—'}</strong><span>Flagged parser limitations</span></div></div>
        {!evidence.data ? <section className="panel empty"><Layers3 size={35}/><h2>Start with a reproducible reference</h2>
          <p>Import the pinned Redmine source, seed a disposable private project, and capture the declared workflows.</p>
          <p className="muted">Docker Desktop must be running. Preparation makes no model requests.</p>
          <button className="primary" disabled={!!live || start.isPending} onClick={() => start.mutate({ kind: 'prepare' })}>
            <Play size={15}/> Prepare reference</button></section> : <div className="evidence-grid"><section className="panel source-panel">
          <div className="panel-title"><FileCode2 size={17}/><h2>Source evidence</h2><span className="count">BM25 retrieval</span></div>
          <div className="source-layout"><div className="source-list">{evidence.data.sources.map((source, index) =>
            <button key={source.evidence_id} className={selected === source ? 'chosen' : ''} onClick={() => setSourceIndex(index)}>
              <span>{source.symbol}</span><small>{source.path.split('/').at(-1)}:{source.start_line}</small></button>)}</div>
            <div className="code-pane"><div className="code-title"><span>{selected?.path}</span><small>L{selected?.start_line}–{selected?.end_line}</small></div>
              <Suspense fallback={<div className="editor-loading" style={{ height: 480 }} aria-busy="true">Loading local syntax viewer…</div>}>
                <CodeViewer height="480px" language="ruby" value={selected?.text ?? ''}/>
              </Suspense></div></div>
          <div className="panel-foot">Each source fact retains its path, line span, and content checksum.</div></section>
          <aside><section className="panel"><div className="panel-title"><ShieldCheck size={17}/><h2>Verification contract</h2></div>
            <div className="contract-item"><Check/> HTTP status, JSON types & headers</div><div className="contract-item"><Check/> Authorization & validation failures</div>
            <div className="contract-item"><Check/> Issue state & journal details</div><div className="contract-item"><Check/> Deterministic wall-clock fields</div>
            <div className="callout">Held-out expectations stay outside model context and candidate containers.</div></section>
            <section className="panel unknowns"><div className="panel-title"><Activity size={17}/><h2>Explicit unknowns</h2></div>
              {evidence.data.unknowns.map(unknown => <p key={unknown}>{unknown}</p>)}</section></aside></div>}
      </>}
      {tab !== 'evidence' && <div className="migration-grid"><aside className="panel configuration"><div className="panel-title"><Layers3 size={17}/><h2>{tab === 'migration' ? 'Migration setup' : 'Candidate runs'}</h2></div>
        {tab === 'migration' && <div className="form"><label>Evidence condition<select value={condition} onChange={e => setCondition(e.target.value as Condition)}>
          <option value="hybrid">Source + runtime</option><option value="source_only">Source only</option><option value="runtime_only">Runtime only</option></select></label>
          <label>Cloud provider<select value={provider} onChange={e => setProvider(e.target.value)}><option value="auto">Groq → Gemini backup</option>
            <option value="groq">Groq · fixed provider</option><option value="gemini">Gemini · fixed provider</option>
            <option value="openrouter">OpenRouter · free models, larger requests</option></select></label>
          {workflow === 'read' && <><label>Generation mode<select value={useStaged ? 'staged' : 'combined'} onChange={e => setStagedRead(e.target.value === 'staged')}>
            <option value="combined">Combined handlers</option><option value="staged" disabled={!stagedEligible}>Separate endpoints · experimental</option></select></label>
            {!stagedEligible && <p className="muted">Separate endpoints require source + runtime and a fixed Groq or Gemini provider.</p>}</>}
          {useStaged && provider === 'groq' && <label>Reasoning effort<select value={reasoning} onChange={e => setReasoning(e.target.value as typeof reasoning)}>
            <option value="low">Low · smaller reasoning budget</option><option value="medium">Medium</option><option value="high">High · larger reasoning budget</option></select></label>}
          <p className="muted">Up to three model requests per run, including repairs and failed calls. Uses your configured free-plan account.
            {useStaged && ' GET and POST are generated separately within that same limit.'}</p>
          <button className="primary full" disabled={!health.data?.prepared || !!live || start.isPending} onClick={() => start.mutate({
            kind: 'migrate', workflow, condition, provider, max_repairs: 2,
            ...(useStaged ? { staged_read: true, ...(provider === 'groq' ? { groq_reasoning_effort: reasoning } : {}) } : {}),
          })}><Play size={15}/> Generate migration</button></div>}
        <div className="run-list-title">SAVED RUNS <span>{runs.data?.length ?? 0}</span></div>
        <div className="run-list">{runs.data?.map(run => <button className={runId === run.run_id ? 'chosen' : ''} key={run.run_id} onClick={() => {
          setRunId(run.run_id); setWorkflow(run.workflow); setCondition(run.condition);
          setSourceIndex(0); setReviewed(false); setProvider(run.provider_policy ?? 'auto'); }}><span><b>{label(run.workflow)}</b><small>{run.run_id.slice(0, 8)}</small></span>
          <small>{label(run.condition)}</small><Status value={runStatus(run)}/></button>)}
          {!runs.data?.length && <p className="muted">No generated runs yet.</p>}</div></aside>
        <section className="panel candidate-panel">{!runId || !data ? <div className="empty"><Braces size={35}/><h2>Select a candidate run</h2>
          <p>Generated source and measured verification results appear here.</p></div> : <>
          <div className="panel-title"><FileCode2 size={17}/><h2>{tab === 'migration' ? 'Generated app.py' : 'Behavior comparison'}</h2>
            <span className="count">{runId.slice(0, 8)}</span>{data.result && <Status value={runStatus(data.result)}/>}</div>
          {tab === 'migration' ? <><Suspense fallback={<div className="editor-loading" style={{ height: 540 }} aria-busy="true">Loading local syntax viewer…</div>}>
            <CodeViewer height="540px" language="python" value={data.source ?? ''}/>
          </Suspense>
            <div className="drafts">{data.result?.attempts.map(attempt => <div key={attempt.attempt}><span className="draft-number">{attempt.attempt + 1}</span>
              <div><b>{attempt.attempt === 0 ? 'Initial generation' : 'Guidance repair'}</b><small>{attempt.provenance.provider} · {attempt.provenance.model}</small>
                {attempt.source_assembly && <small>Controller setup · Model code starts at line {attempt.source_assembly.model_first_line}</small>}</div>
              {attempt.repair_rollback && <small>Patch failed syntax review; next repair uses the prior source.</small>}
              <Status value={attempt.evaluation_status}/></div>)}</div>
            {budget && <p className="muted">Model requests: {budget.reserved_requests + budget.legacy_requests_consumed} / {budget.call_limit}; {budget.remaining} remaining.</p>}
            {(exhausted || data.result?.stop_reason === 'request_budget_exhausted') && <p role="status">Request limit reached. No further automatic calls will be made for this run.</p>}
            {!exhausted && ['provider_paused', 'provider_failed'].includes(data.result?.status ?? '') &&
              (data.result?.failure?.retryable !== false || data.result?.failure?.local_rebuild_available === true) && <div className="finalize">
              <p>{data.result?.failure?.local_rebuild_available ?
                <>The repair prompt exceeded its local size limit. No provider request was sent for that repair. Resume with the saved draft and a compact feedback summary.</> :
                <>The provider stopped before producing this draft. Failure: <code>{data.result?.failure?.category}</code>. The request history is saved; retry sends a new model request.</>}</p>
              <button className="primary" disabled={!!live || start.isPending} onClick={() => start.mutate({
                kind: 'migrate', workflow: data.result?.workflow, condition: data.result?.condition,
                provider: data.result?.provider_policy ?? provider,
                max_repairs: data.result?.max_repairs ?? 2, run_id: runId, retry_failed_call: true,
                ...(data.generation_settings?.staged_read ? { staged_read: true,
                  ...(data.result?.provider_policy === 'groq' ? { groq_reasoning_effort: data.generation_settings.groq_reasoning_effort } : {}),
                } : {}),
              })}><Play size={15}/>{data.result?.failure?.local_rebuild_available ? 'Resume bounded repair' : 'Retry failed provider call'}</button></div>}
            </> : <>
            <div className="verification-overview"><div><h3>Measured scenario matches</h3><p className="muted">A finished job does not imply a verified migration.</p>
              <ResponsiveContainer width="100%" height={160}><BarChart data={chart} layout="vertical" margin={{ left: 0, right: 25 }}>
                <CartesianGrid stroke="#e9ecea" horizontal={false}/><XAxis type="number" allowDecimals={false}/><YAxis type="category" dataKey="name" width={75}/>
                <Tooltip/><Bar dataKey="matched" stackId="a" fill="#358c70" barSize={17}/><Bar dataKey="different" stackId="a" fill="#cf756b" barSize={17}/></BarChart></ResponsiveContainer></div>
              <div className="security-note"><ShieldCheck size={23}/><b>Compatibility ≠ security certification</b><p>Static capability checks and container isolation are separate from functional matches. Production hardening remains a review responsibility.</p></div></div>
            <Results title="Guidance verification" report={latest}/><Results title="Final held-out verification" report={data.held_out}/>
            {!data.held_out && <div className="finalize"><p>Freeze this candidate and check unseen scenarios. These results never feed its repair loop.</p>
              <button className="primary" disabled={data.result?.status !== 'passed' || !!live || start.isPending} onClick={() => start.mutate({ kind: 'finalize', run_id: runId })}>
                <FlaskConical size={16}/> Run final verification</button></div>}
            {data.held_out?.status === 'passed' && <div className="approval"><h3>Review & export</h3><p className="muted">Approval is tied to this exact source checksum.</p>
              {data.approval ? <><p>Reviewed by <b>{data.approval.reviewer}</b></p><a className="primary" href={`/api/runs/${runId}/export`}><ArrowDownToLine size={16}/> Download reviewed source</a></> :
                <><div className="review-inputs"><label>Reviewer<input value={reviewer} onChange={e => setReviewer(e.target.value)}/></label>
                  <label>Review notes<input value={notes} onChange={e => setNotes(e.target.value)}/></label></div>
                  <label className="checkbox"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/>
                    I reviewed the generated source and its stated limitations.</label>
                  <button className="primary" disabled={!reviewed || !reviewer.trim() || !notes.trim() || approve.isPending} onClick={() => approve.mutate()}>
                    <ShieldCheck size={16}/> Approve this source</button></> }</div>}
          </> }</> }</section></div>}
      <section className="panel activity"><div className="panel-title"><Terminal size={17}/><h2>Recent activity</h2><span className="count">Persistent job history</span></div>
        {jobs.data?.slice(0, 5).map(job => <div className="activity-row" key={job.id}><span className="activity-icon"><Terminal size={15}/></span>
          <div><b>{label(job.kind)}</b><span>{job.message}</span></div><Status value={job.state}/><time>{new Date(job.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div>)}
        {!jobs.data?.length && <p className="muted activity-empty">No jobs recorded. Prepare the reference to begin.</p>}</section>
      <footer className="page-footer">LegacyLift <span>Selected workflow modernization · local research workbench</span><span>Contract {health.data?.contract.version ?? '—'}</span></footer>
    </div></main></div>;
}
