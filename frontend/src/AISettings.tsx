import { useEffect, useState } from "react";
import {
  CheckCircle2,
  FileSearch,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  Save,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { api } from "./api";
import { clearAIJob, readAIJob, saveAIJob } from "./persistence";
import type { AIConfig, AIJob, AITask } from "./ai-types";
import type { Workspace } from "./types";

const taskInfo: { id: AITask; label: string }[] = [
  {
    id: "extraction",
    label: "Document extraction",
  },
  {
    id: "vision",
    label: "Scanned pages",
  },
  {
    id: "matching",
    label: "Item equivalence",
  },
  {
    id: "policy",
    label: "Policy interpretation",
  },
  {
    id: "review",
    label: "Reviewer brief",
  },
];
const tokenPrice = (value: string) =>
  new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(
    Number(value),
  );

type Model = {
  id: string;
  name: string;
  vision: boolean;
  input_per_million: string;
  output_per_million: string;
};
type Props = {
  workspace: Workspace;
  update: (w: Workspace) => void;
  notify: (s: string, error?: boolean) => void;
};

export function ReprocessButton({
  documentId,
  update,
  notify,
  disabled = false,
}: {
  documentId?: string;
  update: (w: Workspace) => void;
  notify: (s: string, error?: boolean) => void;
  disabled?: boolean;
}) {
  const [job, setJob] = useState<AIJob | null>(null);
  const [jobId, setJobId] = useState<string | null>(() => readAIJob(documentId));
  const [busy, setBusy] = useState(() => !!readAIJob(documentId));
  useEffect(() => {
    if (!jobId) return;
    let active = true;
    const poll = async () => {
      try {
        const result = await api<AIJob>(`/ai/jobs/${jobId}`);
        if (!active) return;
        setJob(result);
        if (result.status !== "running") {
          clearAIJob(documentId);
          setJobId(null);
          setBusy(false);
          update(await api<Workspace>("/workspace"));
          notify(
            result.errors.length
              ? `AI processing finished with ${result.errors.length} error(s). Original facts were retained for failed files.`
              : `AI processing finished. ${result.skipped} human-verified invoice(s) preserved.`,
            result.errors.length > 0,
          );
        }
      } catch (e) {
        if (active) {
          clearAIJob(documentId);
          setJobId(null);
          setBusy(false);
          notify((e as Error).message, true);
        }
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 1800);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [jobId]);
  const start = async () => {
    setBusy(true);
    try {
      const result = await api<AIJob>("/ai/reprocess", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_ids: documentId ? [documentId] : null,
        }),
      });
      saveAIJob(documentId, result.id);
      setJob(result);
      setJobId(result.id);
    } catch (e) {
      setBusy(false);
      notify((e as Error).message, true);
    }
  };
  return (
    <div className="ai-reprocess">
      <button
        className="button secondary small"
        disabled={disabled || busy}
        onClick={() => void start()}
      >
        {busy ? (
          <LoaderCircle className="spin" size={14} />
        ) : (
          <RefreshCw size={14} />
        )}{" "}
        {documentId ? "Re-extract with AI" : "Reprocess existing invoices"}
      </button>
      {job && (
        <div className="ai-job" role="status">
          <span>
            {job.status === "running"
              ? `Processing ${job.completed}/${job.total} · ${job.current_file || "Preparing…"}`
              : `Processed ${job.completed}/${job.total}`}
          </span>
          <progress value={job.completed} max={job.total} />
          {job.warnings.map((w, i) => (
            <small key={i}>
              {w.filename}: {w.message}
            </small>
          ))}
          {job.errors.map((e, i) => (
            <small className="danger-text" key={i}>
              {e.filename}: {e.message}
            </small>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AISettings({ workspace, update, notify }: Props) {
  const [config, setConfig] = useState<AIConfig | null>(
    workspace.ai_settings || null,
  );
  const [models, setModels] = useState<Model[]>([]);
  const [catalogError, setCatalogError] = useState("");
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [removeKey, setRemoveKey] = useState(false);
  const loadModels = async () => {
    try {
      const result = await api<{ models: Model[] }>("/ai/models");
      setModels(result.models);
      setCatalogError("");
    } catch (e) {
      setCatalogError((e as Error).message);
    }
  };
  useEffect(() => {
    void api<AIConfig>("/ai/settings")
      .then(setConfig)
      .catch((e) => notify((e as Error).message, true));
    void loadModels();
  }, []);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!config) return;
    setSaving(true);
    try {
      const result = await api<AIConfig>("/ai/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: config.enabled,
          api_key: key || null,
          remove_api_key: removeKey,
          models: config.models,
          vision_enabled: config.vision_enabled,
          matching_enabled: config.matching_enabled,
          max_vision_pages: config.max_vision_pages,
          max_output_tokens: config.max_output_tokens,
          timeout_seconds: config.timeout_seconds,
        }),
      });
      setConfig(result);
      setKey("");
      setRemoveKey(false);
      update(await api<Workspace>("/workspace"));
      notify(
        "AI settings saved. Existing extractions are unchanged until you reprocess them.",
      );
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setSaving(false);
    }
  };
  const test = async () => {
    setTesting(true);
    try {
      const result = await api<{ message: string }>("/ai/test", {
        method: "POST",
      });
      notify(result.message);
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setTesting(false);
    }
  };
  if (!config)
    return (
      <div className="loading-panel">
        <LoaderCircle className="spin" />
        Loading AI settings…
      </div>
    );
  return (
    <div className="ai-settings-layout">
      <form className="policy-form" onSubmit={(e) => void save(e)}>
        <div className="queue-heading">
          <div>
            <h2>
              <Sparkles size={19} />
              OpenRouter models
            </h2>
          </div>
          <span className={`neutral-tag ${config.ready ? "ai-ready" : ""}`}>
            {config.ready ? "Configured" : "Key needed"}
          </span>
        </div>
        <div className="policy-body">
          <div className="ai-data-note">
            <ShieldCheck size={18} />
            <p>
              When enabled, invoice and PO text, selected scanned-page images,
              relevant PO item descriptions, and uploaded policy text are sent
              through OpenRouter to the selected model providers. Amount checks
              and final routing run locally.
            </p>
          </div>
          <label className="form-label">
            <span>
              <KeyRound size={13} />
              OpenRouter API key
            </span>
            <input
              type="password"
              autoComplete="new-password"
              spellCheck={false}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={
                config.key_configured
                  ? "A key is saved. Leave blank to keep it."
                  : "Enter your OpenRouter key here"
              }
            />
            <small>
              The saved key is never returned to the browser, included in
              exports, or stored in browser storage.
            </small>
          </label>
          {config.key_configured && (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={removeKey}
                onChange={(e) => {
                  setRemoveKey(e.target.checked);
                  if (e.target.checked)
                    setConfig({ ...config, enabled: false });
                }}
              />
              Remove the saved key on save
            </label>
          )}
          <label className="toggle-row">
            <div>
              <strong>Enable OpenRouter processing</strong>
              <span>
                Use the chosen models for new uploads and explicit reprocessing.
              </span>
            </div>
            <input
              type="checkbox"
              checked={config.enabled}
              onChange={(e) =>
                setConfig({ ...config, enabled: e.target.checked })
              }
            />
          </label>
          <div className="ai-model-heading">
            <h3>Models by task</h3>
            <button
              type="button"
              className="text-link"
              onClick={() => setConfig({ ...config, models: config.defaults })}
            >
              Use budget defaults
            </button>
          </div>
          {catalogError && (
            <p className="field-help">
              {catalogError}{" "}
              <button
                type="button"
                className="text-link"
                onClick={() => void loadModels()}
              >
                Retry catalogue
              </button>
            </p>
          )}
          {taskInfo.map((task) => {
            const selected = models.find(
              (m) => m.id === config.models[task.id],
            );
            return (
              <div className="ai-model-row" key={task.id}>
                <label className="form-label">
                  {task.label}
                  <input
                    required
                    list={`ai-models-${task.id}`}
                    value={config.models[task.id]}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        models: { ...config.models, [task.id]: e.target.value },
                      })
                    }
                  />
                  <datalist id={`ai-models-${task.id}`}>
                    {models
                      .filter((m) => task.id !== "vision" || m.vision)
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name} · ${tokenPrice(m.input_per_million)}/$
                          {tokenPrice(m.output_per_million)} per 1M tokens
                        </option>
                      ))}
                  </datalist>
                </label>
                {selected && (
                  <div className="model-price">
                    <span>${tokenPrice(selected.input_per_million)} input</span>
                    <span>
                      ${tokenPrice(selected.output_per_million)} output / 1M
                      tokens
                    </span>
                    {task.id === "vision" && !selected.vision && (
                      <strong>Choose a model supporting images.</strong>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          <div className="form-grid">
            <label className="form-label">
              Maximum scanned pages per invoice
              <input
                required
                type="number"
                min={1}
                max={15}
                value={config.max_vision_pages}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    max_vision_pages: Number(e.target.value),
                  })
                }
              />
            </label>
            <label className="form-label">
              Maximum output tokens per call
              <input
                required
                type="number"
                min={512}
                max={16000}
                step={1}
                value={config.max_output_tokens}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    max_output_tokens: Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={config.vision_enabled}
              onChange={(e) =>
                setConfig({ ...config, vision_enabled: e.target.checked })
              }
            />
            Use image models for scanned pages
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={config.matching_enabled}
              onChange={(e) =>
                setConfig({ ...config, matching_enabled: e.target.checked })
              }
            />
            Use AI for non-exact invoice/PO item descriptions
          </label>
          <div className="form-actions">
            <button
              type="button"
              className="button secondary"
              disabled={testing || !config.key_configured}
              onClick={() => void test()}
            >
              {testing ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <CheckCircle2 size={14} />
              )}
              Test saved key
            </button>
            <button className="button primary" type="submit" disabled={saving}>
              {saving ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <Save size={14} />
              )}
              Save AI settings
            </button>
          </div>
        </div>
      </form>
      <aside className="ai-settings-aside">
        <section className="ai-reprocess-card">
          <h3>
            <RefreshCw size={16} />
            Existing invoices
          </h3>
          <p>
            Re-extract uploaded PDFs with the saved model choices. This uses
            your OpenRouter credits. Human-verified extractions are preserved.
          </p>
          <ReprocessButton
            update={update}
            notify={notify}
            disabled={!config.ready || !workspace.reviews.length}
          />
        </section>
      </aside>
      <PolicyDrafts workspace={workspace} update={update} notify={notify} />
    </div>
  );
}

function PolicyDrafts({ workspace, update, notify }: Props) {
  const drafts = Object.entries(workspace.reference_drafts || {});
  const [editing, setEditing] = useState<string | null>(null);
  const [json, setJson] = useState("");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const approve = async (id: string) => {
    setBusy(true);
    try {
      const policy = JSON.parse(json);
      update(
        await api<Workspace>(`/ai/policy-drafts/${id}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ policy, note }),
        }),
      );
      setEditing(null);
      notify("Reviewed policy activated. All recommendations recomputed.");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  if (!drafts.length) return null;
  return (
    <section className="ai-policy-drafts">
      <div className="queue-heading">
        <div>
          <h2>
            <FileSearch size={18} />
            Policy interpretations awaiting review
          </h2>
        </div>
      </div>
      {drafts.map(([id, draft]) => (
        <div className="ai-policy-draft" key={id}>
          <h3>
            {workspace.documents.find((d) => d.id === id)?.filename ||
              "Policy document"}
          </h3>
          <p className="field-help">Model: {draft.run.model}</p>
          {Object.entries(draft.sources).map(([field, source]) => (
            <div className="source-card" key={field}>
              <strong>
                {field.replaceAll("_", " ")}:{" "}
                {String(
                  draft.changed_fields[
                    field as keyof typeof draft.changed_fields
                  ],
                )}
              </strong>
              <blockquote>{source.excerpt}</blockquote>
              <a href={`/api/documents/${id}`} target="_blank" rel="noreferrer">
                Inspect original source
              </a>
            </div>
          ))}
          {draft.uncertainties.map((item, i) => (
            <p className="inline-error" key={i}>
              {item}
            </p>
          ))}
          {editing !== id ? (
            <button
              className="button secondary"
              onClick={() => {
                setEditing(id);
                setJson(JSON.stringify(draft.values, null, 2));
                setNote("");
                setConfirmed(false);
              }}
            >
              Review proposed rules
            </button>
          ) : (
            <>
              <label className="form-label">
                Proposed policy (edit any incorrect values)
                <textarea
                  className="json-editor"
                  rows={16}
                  value={json}
                  onChange={(e) => setJson(e.target.value)}
                />
              </label>
              <label className="form-label">
                Review note
                <textarea
                  rows={2}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Explain what you checked and any changes."
                />
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                I checked the proposed rules and resolved the listed
                uncertainties against the source.
              </label>
              <button
                className="button primary"
                disabled={!confirmed || note.trim().length < 5 || busy}
                onClick={() => void approve(id)}
              >
                {busy ? (
                  <LoaderCircle className="spin" size={14} />
                ) : (
                  <CheckCircle2 size={14} />
                )}
                Activate reviewed policy
              </button>
            </>
          )}
        </div>
      ))}
    </section>
  );
}
