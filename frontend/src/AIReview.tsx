import { useState } from "react";
import {
  CheckCircle2,
  CircleAlert,
  LoaderCircle,
  Sparkles,
} from "lucide-react";
import { api } from "./api";
import { ReprocessButton } from "./AISettings";
import type { AIRun } from "./ai-types";
import type { Review, Workspace } from "./types";

export default function AIReview({
  review,
  enabled,
  update,
  notify,
}: {
  review: Review;
  enabled: boolean;
  update: (w: Workspace) => void;
  notify: (s: string, error?: boolean) => void;
}) {
  const [busy, setBusy] = useState("");
  const [confirming, setConfirming] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const analysis = review.ai_analysis || {};
  const matching = analysis.matching;
  const runs: AIRun[] = [
    ...(analysis.extraction_runs || []),
    ...(matching?.run ? [matching.run] : []),
    ...(analysis.brief?.run ? [analysis.brief.run] : []),
  ];
  const confirm = async (invoiceLine: number, poLine: number) => {
    if (!matching) return;
    setBusy(`confirm-${invoiceLine}`);
    try {
      update(
        await api<Workspace>(`/reviews/${review.id}/semantic-confirmation`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            analysis_key: matching.analysis_key,
            invoice_line: invoiceLine,
            po_line: poLine,
            note,
          }),
        }),
      );
      setConfirming(null);
      setNote("");
      notify(
        "Item equivalence confirmed. Exact amount, rate, and quantity checks were rerun.",
      );
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy("");
    }
  };
  const brief = async () => {
    setBusy("brief");
    try {
      update(
        await api<Workspace>(`/reviews/${review.id}/ai-brief`, {
          method: "POST",
        }),
      );
      notify("AI brief generated from the existing checks.");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy("");
    }
  };
  return (
    <section className="ai-review-section">
      <div className="ai-section-title">
        <h3>
          <Sparkles size={16} />
          AI assistance
        </h3>
        <span>
          {runs.filter((r) => r.status === "completed").length} completed
          call(s)
        </span>
      </div>
      {!runs.length && (
        <p className="field-help">
          {enabled
            ? "This invoice has no recorded AI extraction yet. Re-extract it using the saved model choices."
            : "Configure OpenRouter in Policies → AI settings to use AI extraction. Current results use local checks."}
        </p>
      )}
      {enabled && (
        <ReprocessButton
          documentId={review.id}
          update={update}
          notify={notify}
        />
      )}
      {matching?.matches
        .filter(
          (m) =>
            m.equivalence === "equivalent" || m.equivalence === "uncertain",
        )
        .map((match) => (
          <div className="ai-match-card" key={match.invoice_line}>
            <div>
              <strong>
                Invoice line {match.invoice_line + 1} ↔{" "}
                {match.po_line !== null
                  ? `PO line ${match.po_line + 1}`
                  : "No confirmed PO item"}
              </strong>
              {match.confirmed ? (
                <span className="ai-confirmed">
                  <CheckCircle2 size={13} />
                  Human confirmed
                </span>
              ) : (
                <span className="neutral-tag">
                  {match.equivalence === "equivalent"
                    ? "Proposed equivalence"
                    : "Uncertain"}
                </span>
              )}
            </div>
            <blockquote>
              <span>Invoice: {match.invoice_quote}</span>
              <span>PO: {match.po_quote || "No supported match"}</span>
            </blockquote>
            <p>{match.reason}</p>
            {!match.confirmed &&
              match.equivalence === "equivalent" &&
              match.po_line !== null &&
              (confirming !== match.invoice_line ? (
                <button
                  className="button secondary small"
                  onClick={() => {
                    setConfirming(match.invoice_line);
                    setNote("");
                  }}
                >
                  Verify this item match
                </button>
              ) : (
                <>
                  <label className="form-label">
                    Verification note
                    <textarea
                      rows={2}
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      placeholder="Confirm the goods/services, units, and scope are equivalent."
                    />
                  </label>
                  <button
                    className="button primary small"
                    disabled={note.trim().length < 5 || !!busy}
                    onClick={() =>
                      void confirm(match.invoice_line, match.po_line!)
                    }
                  >
                    {busy === `confirm-${match.invoice_line}` ? (
                      <LoaderCircle className="spin" size={13} />
                    ) : (
                      <CheckCircle2 size={13} />
                    )}
                    Confirm equivalence & rerun
                  </button>
                </>
              ))}
          </div>
        ))}
      {analysis.brief ? (
        <div className="ai-brief">
          <h4>AI reviewer brief</h4>
          {analysis.brief.observations.map((item, index) => (
            <p key={index}>
              {item.text}
              <small>Checks: {item.check_codes.join(", ")}</small>
            </p>
          ))}
          <h4>Suggested next steps</h4>
          {analysis.brief.next_steps.map((item, index) => (
            <p key={index}>
              {item.text}
              <small>Checks: {item.check_codes.join(", ")}</small>
            </p>
          ))}
          <span className="field-help">
            Generated interpretation; verify the underlying checks below.
          </span>
        </div>
      ) : (
        enabled && (
          <button
            className="button secondary small"
            disabled={!!busy}
            onClick={() => void brief()}
          >
            {busy === "brief" ? (
              <LoaderCircle className="spin" size={13} />
            ) : (
              <Sparkles size={13} />
            )}
            Generate reviewer brief
          </button>
        )
      )}
      {runs.length > 0 && (
        <details className="ai-trace">
          <summary>
            <Sparkles size={13} />
            Models, usage & failures
          </summary>
          {runs.map((run, index) => (
            <div
              key={index}
              className={`ai-run ${run.status === "failed" ? "failed" : ""}`}
            >
              <div>
                {run.status === "completed" ? (
                  <CheckCircle2 size={13} />
                ) : (
                  <CircleAlert size={13} />
                )}
                <strong>{run.task}</strong>
                <span>{run.status}</span>
              </div>
              <p>{run.model}</p>
              {run.message && <p>{run.message}</p>}
              {run.status === "completed" && (
                <small>
                  {run.prompt_tokens || 0} input + {run.completion_tokens || 0}{" "}
                  output tokens ·{" "}
                  {run.cost_usd != null
                    ? `$${run.cost_usd.toFixed(6)} reported cost`
                    : "Cost not reported by provider"}
                  {run.duration_ms
                    ? ` · ${(run.duration_ms / 1000).toFixed(1)}s`
                    : ""}
                </small>
              )}
            </div>
          ))}
        </details>
      )}
    </section>
  );
}
