import { useEffect, useState } from "react";
import { ArrowRight, Check, Circle, CircleAlert, FileText, LoaderCircle, ShieldCheck, Sparkles } from "lucide-react";
import type { ProcessingEvent, UploadJob } from "./types";
import { readUploadFile, saveUploadFile } from "./persistence";

const stages = [
  ["validation", "Receive"], ["reading", "Read pages"],
  ["extraction", "Extract"], ["matching", "Match records"],
  ["verification", "Verify"], ["recommendation", "Recommend"],
];
const decisionLabels: Record<string, string> = {
  ready: "Ready for approval", clarification: "Needs clarification",
  procurement: "Procurement review", hold: "Hold for investigation",
};
const time = (value: string) => new Date(value).toLocaleTimeString("en-IN", { hour12: false });

export function ProcessingTrace({ events, live = false, failed = false, reference = false }: {
  events: ProcessingEvent[]; live?: boolean; failed?: boolean; reference?: boolean;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);
  const last = events.at(-1);
  const checks = events.filter(e => e.code);
  const attention = checks.filter(e => e.status === "fail" || e.status === "warning");
  const ai = events.filter(e => e.stage === "ai");
  const recommendation = events.find(e => e.stage === "recommendation");
  const waitingAI = [...ai].reverse().find(e => e.status === "running" &&
    !ai.some(f => f.task === e.task && f.timestamp >= e.timestamp && f.status !== "running"));
  const flow = reference ? stages.filter(([id]) => ["validation", "reading", "extraction", "matching"].includes(id)) : stages;
  return <div className="processing-trace">
    <ol className="process-flow" aria-label="Document processing stages">
      {flow.map(([id, label]) => {
        const group = events.filter(e => e.stage === id);
        const complete = group.some(e => e.status === "completed");
        const broken = group.some(e => e.status === "failed") || (failed && group.length > 0 && !complete);
        const active = !complete && !broken && group.some(e => e.status === "running") && live;
        const state = broken ? "failed" : complete ? "completed" : active ? "active" : "pending";
        return <li key={id} className={state} aria-current={active ? "step" : undefined}>
          <span>{broken ? <CircleAlert size={16} /> : complete ? <Check size={16} /> : active ? <LoaderCircle className="spin" size={16} /> : <Circle size={14} />}</span>
          <strong>{label}</strong><small>{broken ? "Stopped" : complete ? "Done" : active ? "In progress" : failed ? "Not reached" : !live && reference ? "Not needed" : "Waiting"}</small>
        </li>;
      })}
    </ol>
    {live && <div className="process-current" role="status">
      {waitingAI ? <Sparkles size={20} /> : <LoaderCircle size={20} className="spin" />}
      <div><strong>{waitingAI ? `AI ${waitingAI.task} in progress` : last?.title || "Waiting to start"}</strong>
        <p>{waitingAI ? waitingAI.model : last?.detail || "Your document is queued for processing."}</p>
        {waitingAI && <small>Waiting for provider · {Math.max(0, Math.floor((now - Date.parse(waitingAI.timestamp)) / 1000))}s elapsed</small>}
      </div>
    </div>}
    {ai.length > 0 && <div className="process-ai">
      <span><Sparkles size={14} /> AI activity</span>
      {[...new Set(ai.map(e => e.task || "extraction"))].map(task => {
        const runs = ai.filter(e => (e.task || "extraction") === task);
        const run = runs.at(-1)!;
        return <div key={task}><strong>{task}</strong><span>{run.model || "Local extraction"}</span>
          <small className={run.status === "warning" ? "attention" : ""}>{run.status === "running" ? "Calling provider…" : run.status === "completed" ? `Response received${run.duration_ms != null ? ` · ${(run.duration_ms / 1000).toFixed(1)}s` : ""}` : run.status === "cached" ? "Saved comparison · no call" : run.status === "skipped" ? "Skipped" : "Needs attention"}</small>
        </div>;
      })}
      <p>AI proposes extracted facts and item matches. Rules determine the recommendation.</p>
    </div>}
    {checks.length > 0 && <div className="process-checks">
      <div className="process-checks-heading"><h4>Verification checks</h4><span>{checks.length} run · {attention.length} need attention</span></div>
      {checks.map((e, i) => <details key={`${e.code}-${i}`} className={`process-check ${e.status}`}>
        <summary>{e.status === "pass" || e.status === "info" ? <Check size={14} /> : <CircleAlert size={14} />}<strong>{e.title}</strong><span>{e.status === "pass" ? "Passed" : e.status === "info" ? "Information" : "Review needed"}</span></summary>
        <p>{e.detail}</p>
        {!!e.evidence?.length && <div className="process-sources">{e.evidence.filter((s, n, all) => s.document_id && all.findIndex(x => x.document_id === s.document_id && x.page === s.page) === n).map((s, n) => <a key={n} href={`/api/documents/${s.document_id}${s.page ? `#page=${s.page}` : ""}`} target="_blank" rel="noreferrer">{s.filename}{s.page ? ` · p${s.page}` : ""}</a>)}</div>}
      </details>)}
    </div>}
    {recommendation && <div className={`process-result ${recommendation.decision}`}>
      <ShieldCheck size={23} /><div><small>RULES-BASED RECOMMENDATION</small><h3>{decisionLabels[recommendation.decision || ""] || recommendation.title}</h3><p>{recommendation.detail}</p><strong>Human review and approval required</strong></div>
    </div>}
    <details className="process-log"><summary>Processing event log <span>{events.length} events</span></summary>
      <ol>{events.map((e, i) => <li key={i} className={e.status}><time dateTime={e.timestamp}>{time(e.timestamp)}</time><div><strong>{e.title}</strong><p>{e.detail}</p></div></li>)}</ol>
    </details>
  </div>;
}

export default function UploadProgress({ job, onReview, onPoDraft }: { job: UploadJob; onReview: (id: string) => void; onPoDraft: (id: string) => void }) {
  const [selected, setSelected] = useState(() => readUploadFile(job.id) || job.files[0]?.id);
  const file = job.files.find(f => f.id === selected) || job.files[0];
  useEffect(() => { if (file) saveUploadFile(job.id, file.id); }, [job.id, file?.id]);
  const live = job.status === "running" || job.status === "queued";
  const finished = job.files.filter(f => f.status === "completed" || f.status === "failed").length;
  return <section className="upload-progress" aria-label="Live document processing">
    <div className="process-heading"><div><span className="eyebrow">{live ? "LIVE PROCESSING" : "PROCESSING RESULTS"}</span><h3>{live ? "Following your document" : job.status === "failed" ? "Processing interrupted" : "Document processing complete"}</h3><p>Actual processing events · {finished} of {job.files.length} files finished</p></div><span className={`process-live ${live ? "active" : ""}`}>{live ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />}{live ? "Live" : "Finished"}</span></div>
    <div className="process-files" role="group" aria-label="Select a document">{job.files.map(f => <button key={f.id} className={file?.id === f.id ? "selected" : ""} aria-pressed={file?.id === f.id} onClick={() => setSelected(f.id)}><FileText size={15} /><span>{f.filename}<small>{f.status === "failed" ? "Could not process" : f.status === "completed" ? "Saved" : f.status === "queued" ? "Queued" : "Processing"}</small></span>{f.status === "completed" && <Check size={14} />}{f.status === "failed" && <CircleAlert size={14} />}</button>)}</div>
    {file && <ProcessingTrace events={file.events} live={live && !["completed", "failed"].includes(file.status)} failed={file.status === "failed" || job.status === "failed"} reference={job.kind !== "invoice"} />}
    {job.errors.length > 0 && <div className="upload-errors" role="alert">{job.errors.map((e, i) => <p key={i}><strong>{e.filename}</strong><br />{e.message}</p>)}</div>}
    {!live && job.status === "completed" && job.kind === "invoice" && file?.status === "completed" && <button className="button primary" onClick={() => onReview(file.id)}>Open invoice review <ArrowRight size={15} /></button>}
    {!live && job.status === "completed" && job.kind === "purchase_orders" && file?.status === "completed" && job.accepted.some((item) => item.id === file.id && item.pending_review) && <button className="button primary" onClick={() => onPoDraft(file.id)}>Review purchase order <ArrowRight size={15} /></button>}
  </section>;
}
