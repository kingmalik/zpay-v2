"use client";

import { useEffect, useState, useCallback, Fragment } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  DollarSign,
  Download,
  Mail,
  Check,
  AlertTriangle,
  RefreshCw,
  ChevronLeft,
  Send,
  SkipForward,
  RotateCcw,
  FileSpreadsheet,
  Users,
  Package,
  Pencil,
  Save,
  Loader2,
  Eye,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import WorkflowStepper from "@/components/ui/WorkflowStepper";
import AlertCard from "@/components/ui/AlertCard";
import Badge from "@/components/ui/Badge";
import StatCard from "@/components/ui/StatCard";
import LoadingSpinner from "@/components/ui/LoadingSpinner";
import { AddAdjustmentButton, ViewAdjustmentsButton } from "@/components/payroll/AddAdjustmentModal";
import PaychexBotPanel from "@/components/payroll/PaychexBotPanel";
import { useCurrentUser } from "@/hooks/useCurrentUser";

// ── Types ──────────────────────────────────────────────────────────────────

interface BatchStatus {
  batch_id: number;
  source: string;
  company: string;
  company_raw: string;
  status: string;
  week_label: string;
  period_start: string | null;
  period_end: string | null;
  rides: number;
  revenue: number;
  cost: number;
  margin: number;
  unpriced_rides: number;
  driver_count: number;
  stubs_sent: number;
  stubs_failed: number;
  next_stage: string | null;
  blockers: string[];
  warnings: string[];
  stage_index: number;
  stages: string[];
  paychex_exported_at: string | null;
}

interface SiblingRoute {
  service_name: string;
  current_rate: number;
  miles: number | null;
  ride_count_30d: number;
  kind: "letter_variant" | "numbered_neighbor" | "opposite_direction";
}

interface RateGroup {
  service_name: string;
  count: number;
  total_net_pay: number;
  drivers: string[];
  suggested_rate: number | null;
  service_id: number | null;
  sibling_routes: SiblingRoute[];
}

interface RatesCheck {
  total_unpriced: number;
  groups: RateGroup[];
}

interface PayrollDriver {
  id: number;
  name: string;
  pay_code: string;
  email: string;
  days: number;
  rides: number;
  miles: number;
  net_pay: number;
  partner_pays: number;
  driver_pay: number;
  deduction: number;
  carried_over: number;
  pay_this_period: number;
  status: string;
  withheld_amount: number;
  force_pay_override?: boolean;
  manual_withhold_note?: string | null;
  missing_paycheck_code?: boolean;
  balance_source?: BalanceSource | null;
  // Paid-externally disposition
  settled_externally?: boolean;
  external_method?: string | null;
  external_amount?: number | null;
  external_note?: string | null;
  settled_at?: string | null;
}

interface LateCancelRide {
  ride_id?: number;
  driver: string;
  route: string;
  z_rate: number;
  net_pay: number;
  ratio: number;
}

interface NetPayChangeRide {
  route: string;
  partner_before: number;
  partner_now: number;
  partner_delta: number;
  driver_before: number;
  driver_now: number;
  driver_delta: number;
  margin_delta: number;
}

interface AffectedPerson {
  person_id: number;
  name: string;
  paycheck_code?: string;
  email?: string;
}

interface NegativeMarginRide {
  ride_id: number;
  driver: string;
  z_rate: number;
  net_pay: number;
  ride_date: string | null;
}

interface NegativeMarginDetail {
  service_name: string;
  z_rate: number;
  net_pay: number;
  count: number;
  drivers?: string[];
  rides?: NegativeMarginRide[];
}

interface PayrollWarning {
  severity: "warning" | "error" | "info";
  title: string;
  description: string;
  type: string;
  count?: number;
  rides?: LateCancelRide[] | NetPayChangeRide[];
  affected?: AffectedPerson[] | NegativeMarginDetail[];
}

interface PayrollPreview {
  drivers: PayrollDriver[];
  withheld: PayrollDriver[];
  settled_externally: PayrollDriver[];
  totals: {
    days: number;
    rides: number;
    miles: number;
    net_pay: number;
    partner_pays: number;
    driver_pay: number;
    deduction: number;
    pay_this_period: number;
  };
  warnings: PayrollWarning[];
  stats: {
    driver_count: number;
    total_pay: number;
    withheld_amount: number;
    withheld_count: number;
    settled_externally_amount: number;
    settled_externally_count: number;
  };
}

interface StubDriver {
  person_id: number;
  name: string;
  email: string | null;
  status: "sent" | "failed" | "no_email" | "withheld" | "settled_externally" | "pending";
  error: string | null;
  sent_at: string | null;
}

interface StubsStatus {
  drivers: StubDriver[];
  counts: {
    sent: number;
    failed: number;
    no_email: number;
    withheld: number;
    settled_externally: number;
    pending: number;
  };
  total: number;
}

// ── Step labels ─────────────────────────────────────────────────────────────

const STEP_LABELS = ["Rates", "Review", "Export", "Stubs", "Done"];
const STAGE_TO_STEP: Record<string, number> = {
  uploaded: 0,
  rates_review: 0,
  payroll_review: 1,
  approved: 2,
  export_ready: 2,
  stubs_sending: 3,
  complete: 4,
};

// ── Helpers ─────────────────────────────────────────────────────────────────

interface BalanceSource {
  batch_id: number;
  period_start: string | null;
  period_end: string | null;
  source: string | null;
  batch_ref: string | null;
  week_number: number | null;
}

function balanceWeekLabel(src: BalanceSource): string {
  if (src.week_number != null) return `Week ${src.week_number}`;
  // fallback: parse batch_ref for maz-style "W14" suffix
  if (src.batch_ref) {
    const m = /W(\d+)/i.exec(src.batch_ref);
    if (m) return `Week ${m[1]}`;
  }
  return "a prior week";
}

function isBatchMaz(status: BatchStatus): boolean {
  const src = status.source?.toLowerCase() ?? ''
  const co = (status.company_raw ?? status.company ?? '').toLowerCase()
  return src === 'maz' || co.includes('maz') || co.includes('ever')
}

// ── Main component ──────────────────────────────────────────────────────────

export default function BatchWorkflowPage() {
  const params = useParams();
  const router = useRouter();
  const batchId = Number(params.batchId);
  const { isAdmin, loading: userLoading } = useCurrentUser();

  const [status, setStatus] = useState<BatchStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [advancing, setAdvancing] = useState(false);
  const [advanceError, setAdvanceError] = useState<string | null>(null);
  const [reopenError, setReopenError] = useState<string | null>(null);
  /** Admin-only: when non-null, overrides the rendered step. All controls remain fully interactive — no disabled state. */
  const [adminViewStep, setAdminViewStep] = useState<number | null>(null);

  const refreshStatus = useCallback(() => {
    return api
      .get<BatchStatus>(`/api/data/workflow/${batchId}/status`)
      .then(setStatus)
      .catch((e) => { console.error(e); toast.error('Failed to refresh batch status') });
  }, [batchId]);

  useEffect(() => {
    refreshStatus().finally(() => setLoading(false));
  }, [refreshStatus]);

  // Clear admin step override whenever the live batch status changes
  useEffect(() => {
    setAdminViewStep(null);
  }, [status?.status]);

  async function handleAdvance(force = false, notes?: string) {
    setAdvancing(true);
    setAdvanceError(null);
    try {
      await api.post(`/api/data/workflow/${batchId}/advance`, { force, notes });
      await refreshStatus();
    } catch (e) {
      console.error(e);
      toast.error('Failed to advance batch');
      let msg = e instanceof Error ? e.message : "Failed to advance batch";
      try {
        const parsed = JSON.parse(msg);
        if (parsed?.blockers?.length) msg = parsed.blockers.join(" · ");
        else if (parsed?.error) msg = parsed.error;
      } catch {
        /* plain string */
      }
      setAdvanceError(msg);
      await refreshStatus();
    } finally {
      setAdvancing(false);
    }
  }

  async function handleReopen() {
    await api.post(`/api/data/workflow/${batchId}/reopen`);
    await refreshStatus();
  }

  async function handleGoBack() {
    if (
      !confirm(
        "Step back to previous stage? This will NOT undo any stubs that were already sent or CSVs downloaded — it only changes the workflow state.",
      )
    ) {
      return;
    }
    try {
      await api.post(`/api/data/workflow/${batchId}/go-back`);
      await refreshStatus();
    } catch (e) {
      console.error(e);
      toast.error('Failed to go back to previous stage');
    }
  }

  async function handleReopenForReview() {
    if (
      !confirm(
        "Reopen this batch for review? This will move it back to the payroll review stage.",
      )
    ) {
      return;
    }
    setReopenError(null);
    try {
      await api.post(`/api/data/workflow/${batchId}/reopen`);
      await refreshStatus();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to reopen batch";
      setReopenError(msg);
    }
  }

  /**
   * Admin stepper navigation.
   * - Clicking a past step: move DB backward (go-back / reopen).
   * - Clicking a future step: set adminViewStep to render that step fully live
   *   (all buttons clickable, all mutations fire) without touching the DB status.
   * - Clicking current step: clear override (back to live view).
   */
  async function handleAdminStepClick(stepIndex: number) {
    if (!isAdmin || !status) return;
    const liveStep = STAGE_TO_STEP[status.status] ?? 0;

    if (stepIndex === liveStep) {
      // Clicked the current live step — clear any preview and return to live view
      setAdminViewStep(null);
      return;
    }

    if (stepIndex > liveStep) {
      // Future step — render fully live, no DB status change
      setAdminViewStep(stepIndex);
      return;
    }

    // Past step — navigate the batch backward via existing API calls
    setAdminViewStep(null);
    const stepsBack = liveStep - stepIndex;
    try {
      if (stepIndex <= 1 && status.status !== "payroll_review" && status.status !== "uploaded" && status.status !== "rates_review") {
        // Reopen jumps directly to payroll_review in one call (step 1)
        await api.post(`/api/data/workflow/${batchId}/reopen`);
        if (stepIndex === 0) {
          // Need one more go-back to get to rates_review
          await api.post(`/api/data/workflow/${batchId}/go-back`);
        }
      } else {
        // Generic: call go-back stepsBack times
        for (let i = 0; i < stepsBack; i++) {
          await api.post(`/api/data/workflow/${batchId}/go-back`);
        }
      }
      await refreshStatus();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Navigation failed";
      setReopenError(msg);
    }
  }

  if (loading || userLoading || !status) return <LoadingSpinner fullPage />;

  const currentStep = STAGE_TO_STEP[status.status] ?? 0;
  /** Step displayed in the stepper — admin override takes precedence over the live step. */
  const displayStep = isAdmin && adminViewStep !== null ? adminViewStep : currentStep;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => router.push("/payroll/workflow")}
          className="p-2 rounded-lg hover:bg-white/10 transition-colors"
        >
          <ChevronLeft className="w-5 h-5 text-white/60" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-white">
              {status.week_label ? `${status.week_label} — ` : ""}
              {status.company} Payroll
            </h1>
            <Badge variant={status.company === "FirstAlt" ? "fa" : "ed"} dot>
              {status.company}
            </Badge>
          </div>
          <p className="text-sm text-white/50 mt-0.5">
            {status.period_start && status.period_end
              ? `${new Date(status.period_start + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} – ${new Date(status.period_end + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`
              : "No period set"}
            {" · "}
            {status.rides} rides · {status.driver_count} drivers
          </p>
        </div>
        {/* Previous Stage button — visible on approved, export_ready, stubs_sending */}
        {(status.status === "approved" ||
          status.status === "export_ready" ||
          status.status === "stubs_sending") && (
          <button
            onClick={handleGoBack}
            className="px-3 py-2 rounded-lg text-sm font-medium text-white/60 hover:text-white hover:bg-white/10 transition-colors inline-flex items-center gap-1.5"
          >
            <ChevronLeft className="w-4 h-4" />
            Previous
          </button>
        )}
      </div>

      {/* Stepper */}
      <div className="mb-10 px-4">
        <WorkflowStepper
          steps={STEP_LABELS}
          currentStep={displayStep}
          onStepClick={isAdmin ? handleAdminStepClick : undefined}
        />
        {/* Admin override banner — informational only, controls remain fully live */}
        {isAdmin && adminViewStep !== null && adminViewStep !== currentStep && (
          <div className="mt-4 flex items-center justify-between gap-3 px-3 py-2 rounded-lg bg-[#667eea]/15 border border-[#667eea]/30 text-xs text-[#a8b4f8]">
            <span>
              Admin override — using <strong>{STEP_LABELS[adminViewStep]}</strong> step. Batch is live at <strong>{STEP_LABELS[currentStep]}</strong>.
            </span>
            <button
              onClick={() => setAdminViewStep(null)}
              className="shrink-0 text-[#667eea] hover:text-white transition-colors"
            >
              Back to live
            </button>
          </div>
        )}
      </div>

      {/* Advance error banner */}
      {advanceError && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-red-500/15 border border-red-500/30 text-red-300 text-sm flex items-start justify-between gap-3">
          <div>
            <div className="font-medium mb-0.5">Can&apos;t advance batch</div>
            <div className="text-red-300/80">{advanceError}</div>
          </div>
          <button
            onClick={() => setAdvanceError(null)}
            className="text-red-300/60 hover:text-red-300 flex-shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Step content — admin can preview future steps without mutating batch state */}
      <AnimatePresence mode="wait">
        <motion.div
          key={isAdmin && adminViewStep !== null ? `preview-${adminViewStep}` : status.status}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.25 }}
        >
          {/* Admin override: fully live step components — no disabled wrapper, no opacity dim */}
          {isAdmin && adminViewStep !== null && adminViewStep !== currentStep && (
            <>
              {(adminViewStep === 0) && (
                <RatesReviewStep
                  batchId={batchId}
                  status={status}
                  onAdvance={handleAdvance}
                  advancing={advancing}
                  onRefresh={refreshStatus}
                  isAdmin={true}
                />
              )}
              {(adminViewStep === 1) && (
                <PayrollReviewStep
                  batchId={batchId}
                  status={status}
                  onAdvance={handleAdvance}
                  advancing={advancing}
                  onRefresh={refreshStatus}
                  isAdmin={true}
                  onReopen={handleReopenForReview}
                  onGoBack={handleGoBack}
                />
              )}
              {(adminViewStep === 2) && (
                <ExportStep
                  batchId={batchId}
                  status={status}
                  onAdvance={handleAdvance}
                  advancing={advancing}
                  isAdmin={true}
                  onReopen={handleReopenForReview}
                />
              )}
              {(adminViewStep === 3) && (
                <StubsStep
                  batchId={batchId}
                  status={status}
                  onAdvance={handleAdvance}
                  advancing={advancing}
                  onRefresh={refreshStatus}
                  isAdmin={true}
                  onReopen={handleReopenForReview}
                />
              )}
              {(adminViewStep === 4) && (
                <CompleteStep
                  status={status}
                  isAdmin={true}
                  onReopen={handleReopenForReview}
                />
              )}
            </>
          )}
          {/* Live step content (always rendered when no admin preview of a future step) */}
          {(!isAdmin || adminViewStep === null || adminViewStep === currentStep) && (
            <>
          {(status.status === "uploaded" ||
            status.status === "rates_review") && (
            <RatesReviewStep
              batchId={batchId}
              status={status}
              onAdvance={handleAdvance}
              advancing={advancing}
              onRefresh={refreshStatus}
              isAdmin={isAdmin}
            />
          )}
          {status.status === "payroll_review" && (
            <PayrollReviewStep
              batchId={batchId}
              status={status}
              onAdvance={handleAdvance}
              advancing={advancing}
              onRefresh={refreshStatus}
              isAdmin={isAdmin}
              onReopen={handleReopenForReview}
              onGoBack={handleGoBack}
            />
          )}
          {(status.status === "approved" ||
            status.status === "export_ready") && (
            <ExportStep
              batchId={batchId}
              status={status}
              onAdvance={handleAdvance}
              advancing={advancing}
              isAdmin={isAdmin}
              onReopen={handleReopen}
            />
          )}
          {status.status === "stubs_sending" && (
            <StubsStep
              batchId={batchId}
              status={status}
              onAdvance={handleAdvance}
              advancing={advancing}
              onRefresh={refreshStatus}
              isAdmin={isAdmin}
              onReopen={handleReopen}
            />
          )}
          {status.status === "complete" && (
            <CompleteStep
              status={status}
              isAdmin={isAdmin}
              onReopen={handleReopen}
            />
          )}
            </>
          )}
        </motion.div>
      </AnimatePresence>

      {/* Bottom action links — go back and reopen */}
      <div className="mt-8 flex flex-col items-center gap-2">
        {status.status !== "uploaded" &&
          status.status !== "rates_review" &&
          status.status !== "complete" && (
            <button
              onClick={handleGoBack}
              className="text-sm text-white/40 hover:text-white/60 transition-colors inline-flex items-center gap-1"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Go back to previous step
            </button>
          )}
        {isAdmin &&
          status.status !== "payroll_review" &&
          status.status !== "uploaded" &&
          status.status !== "rates_review" && (
            <div>
              <button
                onClick={handleReopenForReview}
                className="text-sm text-white/40 hover:text-white/60 transition-colors inline-flex items-center gap-1"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
                Reopen for review
              </button>
              {reopenError && (
                <p className="text-xs text-rose-400 mt-1">{reopenError}</p>
              )}
            </div>
          )}
      </div>
    </div>
  );
}

// ── Admin utility: Reset Batch to Review button ─────────────────────────────

function AdminResetButton({ onReopen }: { onReopen: () => Promise<void> }) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  async function handleReset() {
    setResetting(true);
    setResetError(null);
    try {
      await onReopen();
      setShowConfirm(false);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Reset failed";
      setResetError(msg);
    } finally {
      setResetting(false);
    }
  }

  if (!showConfirm) {
    return (
      <div className="mt-4 text-center">
        <button
          onClick={() => setShowConfirm(true)}
          className="text-xs text-white/30 hover:text-rose-400 transition-colors inline-flex items-center gap-1"
        >
          <RotateCcw className="w-3 h-3" />
          Reset batch to Review
        </button>
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/8 p-4 max-w-sm mx-auto text-left">
      <p className="text-sm font-medium text-rose-300 mb-1">Reset to Review?</p>
      <p className="text-xs text-white/50 mb-3">
        This wipes calculated balances and clears export timestamps. Cannot be done if real stubs were already sent.
      </p>
      {resetError && (
        <p className="text-xs text-rose-400 mb-2">{resetError}</p>
      )}
      <div className="flex items-center gap-3">
        <button
          onClick={() => { setShowConfirm(false); setResetError(null); }}
          className="px-3 py-1.5 rounded-lg text-xs text-white/50 hover:text-white transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleReset}
          disabled={resetting}
          className="px-4 py-1.5 rounded-lg text-xs font-medium bg-rose-500/20 text-rose-300 hover:bg-rose-500/30 border border-rose-500/30 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
        >
          {resetting ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
          {resetting ? "Resetting..." : "Yes, reset"}
        </button>
      </div>
    </div>
  );
}

// ── Step 1: Rates Review ────────────────────────────────────────────────────

function RatesReviewStep({
  batchId,
  status,
  onAdvance,
  advancing,
  onRefresh,
  isAdmin = false,
}: {
  batchId: number;
  status: BatchStatus;
  onAdvance: (force?: boolean) => void;
  advancing: boolean;
  onRefresh: () => Promise<void>;
  isAdmin?: boolean;
}) {
  const [data, setData] = useState<RatesCheck | null>(null);
  const [loading, setLoading] = useState(true);
  const [rateInputs, setRateInputs] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [showForceConfirm, setShowForceConfirm] = useState(false);

  useEffect(() => {
    api
      .get<RatesCheck>(`/api/data/workflow/${batchId}/rates-check`)
      .then((d) => {
        setData(d);
        // Pre-fill with suggested rates
        const inputs: Record<string, string> = {};
        d.groups.forEach((g) => {
          if (g.suggested_rate)
            inputs[g.service_name] = g.suggested_rate.toString();
        });
        setRateInputs(inputs);
      })
      .catch((e) => { console.error(e); toast.error('Failed to load rates check') })
      .finally(() => setLoading(false));
  }, [batchId]);

  async function applyRate(serviceName: string, serviceId: number | null) {
    const rate = parseFloat(rateInputs[serviceName] || "0");
    if (!rate || rate <= 0) return;

    setSaving(serviceName);
    try {
      if (serviceId) {
        // Update existing rate service
        await api.post(`/api/data/rates/${serviceId}/set`, { rate });
      } else {
        // Create new rate service via the workflow endpoint
        await api.post("/api/data/workflow/rates/create", {
          service_name: serviceName,
          source: status.source,
          company_name: status.company_raw,
          default_rate: rate,
        });
      }
      // Recalculate rides for this batch with the new rate
      await api.post(`/api/data/workflow/rates/apply-batch/${batchId}`);
      // Refresh
      const d = await api.get<RatesCheck>(
        `/api/data/workflow/${batchId}/rates-check`,
      );
      setData(d);
      await onRefresh();
    } catch (e) {
      console.error(e);
      toast.error('Failed to apply rate');
    } finally {
      setSaving(null);
    }
  }

  if (loading) return <LoadingSpinner />;

  const totalUnpriced = data?.total_unpriced || 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Rates Review</h2>
        <Badge variant={totalUnpriced === 0 ? "success" : "danger"} dot>
          {totalUnpriced === 0
            ? "All priced"
            : `${totalUnpriced} unpriced rides`}
        </Badge>
      </div>

      {totalUnpriced === 0 ? (
        <div className="text-center py-8">
          <Check className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
          <p className="text-white/70 mb-4">All rides have rates assigned.</p>
          <button
            onClick={() => onAdvance()}
            disabled={advancing}
            className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
          >
            {advancing ? "Advancing..." : "Continue to Payroll Review"}
          </button>
        </div>
      ) : (
        <>
          <div className="space-y-3 mb-6">
            {data?.groups.map((group, idx) => (
              <div
                key={group.service_name}
                className="rounded-xl p-4 dark:bg-white/5 dark:border dark:border-white/10"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">
                      {group.service_name}
                    </p>
                    <p className="text-xs text-white/40 mt-0.5">
                      {group.count} rides ·{" "}
                      {formatCurrency(group.total_net_pay)} company rate ·{" "}
                      {group.drivers.slice(0, 3).join(", ")}
                      {group.drivers.length > 3
                        ? ` +${group.drivers.length - 3}`
                        : ""}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-white/40">$</span>
                    <input
                      type="number"
                      step="1"
                      min="0"
                      value={rateInputs[group.service_name] || ""}
                      onChange={(e) =>
                        setRateInputs((prev) => ({
                          ...prev,
                          [group.service_name]: e.target.value,
                        }))
                      }
                      placeholder="Rate"
                      className="w-20 px-2 py-1.5 rounded-lg text-sm text-white bg-white/10 border border-white/20 focus:border-[#667eea] focus:outline-none text-right"
                    />
                    <button
                      onClick={() =>
                        applyRate(group.service_name, group.service_id)
                      }
                      disabled={
                        saving === group.service_name ||
                        !rateInputs[group.service_name]
                      }
                      className="px-3 py-1.5 rounded-lg text-xs font-medium bg-[#667eea] text-white hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
                    >
                      {saving === group.service_name ? "..." : "Apply"}
                    </button>
                  </div>
                </div>
                {/* Sibling route context */}
                {group.sibling_routes && group.sibling_routes.length > 0 ? (
                  <SiblingRoutesDetail
                    siblings={group.sibling_routes}
                    groupIndex={idx}
                    onUseRate={(rate) =>
                      setRateInputs((prev) => ({
                        ...prev,
                        [group.service_name]: rate.toString(),
                      }))
                    }
                  />
                ) : group.sibling_routes && group.sibling_routes.length === 0 && !group.suggested_rate ? (
                  <p className="mt-2 text-xs text-white/20 italic">
                    First time this school has appeared in Z-Pay — no rate precedent.
                  </p>
                ) : null}
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between">
            {/* Admin-only force-advance bypass — hidden from operators/associates */}
            {isAdmin ? (
              <>
                {showForceConfirm ? (
                  <div className="flex-1 mr-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200">
                    <p className="font-semibold mb-1">
                      Advance with {totalUnpriced} unpriced ride{totalUnpriced !== 1 ? "s" : ""}?
                    </p>
                    <p className="text-amber-200/70 mb-2">
                      Affected drivers will pay $0 this week and need a W-adjustment to be made whole:{" "}
                      <span className="text-amber-100">
                        {Array.from(
                          new Set(
                            (data?.groups ?? []).flatMap((g) => g.drivers)
                          )
                        )
                          .slice(0, 8)
                          .join(", ")}
                        {Array.from(
                          new Set(
                            (data?.groups ?? []).flatMap((g) => g.drivers)
                          )
                        ).length > 8
                          ? ` +${Array.from(new Set((data?.groups ?? []).flatMap((g) => g.drivers))).length - 8} more`
                          : ""}
                      </span>
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => { setShowForceConfirm(false); onAdvance(true); }}
                        disabled={advancing}
                        className="px-3 py-1 rounded-lg text-xs font-medium bg-amber-500/30 text-amber-100 hover:bg-amber-500/50 transition-colors disabled:opacity-50"
                      >
                        {advancing ? "Advancing..." : "Yes, advance with $0 rates"}
                      </button>
                      <button
                        onClick={() => setShowForceConfirm(false)}
                        disabled={advancing}
                        className="px-3 py-1 rounded-lg text-xs font-medium text-white/40 hover:text-white/70 transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowForceConfirm(true)}
                    disabled={advancing}
                    className="text-sm text-amber-400/60 hover:text-amber-300 transition-colors inline-flex items-center gap-1"
                  >
                    <SkipForward className="w-3.5 h-3.5" />
                    Skip with $0 rates (admin override)
                  </button>
                )}
              </>
            ) : (
              /* Non-admin: empty left side — the advance button on the right stays disabled */
              <span />
            )}
            <button
              onClick={() => onAdvance()}
              disabled={advancing || totalUnpriced > 0}
              className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
            >
              Continue to Payroll Review
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ── Late cancellation detail (expandable) ──────────────────────────────────

function LateCancellationDetail({
  batchId,
  rides,
  onSaved,
}: {
  batchId: number;
  rides: LateCancelRide[];
  onSaved?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [values, setValues] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState<number | null>(null);
  const [saved, setSaved] = useState<Set<number>>(new Set());
  const [errors, setErrors] = useState<Record<number, string>>({});

  async function saveRide(ride: LateCancelRide) {
    if (!ride.ride_id) return;
    const rate = parseFloat(values[ride.ride_id] || "");
    if (isNaN(rate) || rate < 0) return;
    setSaving(ride.ride_id);
    setErrors((prev) => { const e = { ...prev }; delete e[ride.ride_id!]; return e; });
    try {
      await api.patch(`/api/data/workflow/${batchId}/update-ride-rate`, {
        ride_id: ride.ride_id,
        z_rate: rate,
        mode: "single_ride",
      });
      setSaved((prev) => new Set(prev).add(ride.ride_id!));
      onSaved?.();
    } catch {
      setErrors((prev) => ({ ...prev, [ride.ride_id!]: "Save failed" }));
    } finally {
      setSaving(null);
    }
  }

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-amber-300/70 hover:text-amber-300 transition-colors underline underline-offset-2"
      >
        {expanded ? "Hide details" : `Show ${rides.length} affected rides`}
      </button>
      {expanded && (
        <div className="mt-2 rounded-lg overflow-hidden bg-black/20 border border-white/5">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-white/40 uppercase">
                <th className="px-3 py-1.5">Driver</th>
                <th className="px-3 py-1.5">Route</th>
                <th className="px-3 py-1.5 text-right">Rate</th>
                <th className="px-3 py-1.5 text-right">Paid</th>
                <th className="px-3 py-1.5 text-right">Ratio</th>
                {rides.some((r) => r.ride_id) && (
                  <th className="px-3 py-1.5 text-right">Override</th>
                )}
              </tr>
            </thead>
            <tbody>
              {rides.map((r, i) => (
                <tr key={r.ride_id ?? i} className="border-t border-white/5">
                  <td className="px-3 py-1.5 text-white/70">{r.driver}</td>
                  <td className="px-3 py-1.5 text-white/50 truncate max-w-[160px]">
                    {r.route}
                  </td>
                  <td className="px-3 py-1.5 text-right text-white/50">
                    {formatCurrency(r.z_rate)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-amber-400">
                    {formatCurrency(r.net_pay)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-white/40">
                    {Math.round(r.ratio * 100)}%
                  </td>
                  {r.ride_id && (
                    <td className="px-3 py-1.5 text-right">
                      {saved.has(r.ride_id) ? (
                        <span className="text-emerald-400 inline-flex items-center gap-1">
                          <Check className="w-3 h-3" />{" "}
                          {formatCurrency(parseFloat(values[r.ride_id] || "0"))}
                        </span>
                      ) : (
                        <div className="inline-flex items-center gap-1.5">
                          <span className="text-white/30">$</span>
                          <input
                            type="number"
                            step="1"
                            min="0"
                            placeholder={String(Math.round(r.net_pay))}
                            value={values[r.ride_id] ?? ""}
                            onChange={(e) =>
                              setValues((prev) => ({
                                ...prev,
                                [r.ride_id!]: e.target.value,
                              }))
                            }
                            onKeyDown={(e) => e.key === "Enter" && saveRide(r)}
                            className="w-16 px-1.5 py-0.5 rounded text-xs text-white bg-white/10 border border-white/20 focus:border-amber-400 focus:outline-none text-right"
                          />
                          <button
                            onClick={() => saveRide(r)}
                            disabled={
                              saving === r.ride_id || !values[r.ride_id]
                            }
                            className="px-2 py-0.5 rounded text-xs font-medium bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 disabled:opacity-40 transition-colors whitespace-nowrap inline-flex items-center gap-1"
                            title="Set rate for this one ride only — does not affect other rides on this route"
                          >
                            {saving === r.ride_id ? (
                              <Loader2 className="w-3 h-3 animate-spin" />
                            ) : (
                              <Save className="w-3 h-3" />
                            )}
                            Just this ride
                          </button>
                          {errors[r.ride_id] && (
                            <span className="text-red-400 text-xs">
                              {errors[r.ride_id]}
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function NetPayChangeDetail({ rides }: { rides: NetPayChangeRide[] }) {
  const [expanded, setExpanded] = useState(false);

  function deltaClass(val: number): string {
    if (val > 0) return "text-emerald-400";
    if (val < 0) return "text-red-400";
    return "text-white/40";
  }

  function marginDeltaClass(val: number): string {
    if (val > 0) return "text-emerald-400 font-semibold";
    if (val < 0) return "text-red-400 font-semibold";
    if (val < -0.01) return "text-yellow-400 font-semibold";
    return "text-white/40";
  }

  function formatDelta(val: number): string {
    if (val === 0) return "—";
    return (val > 0 ? "+" : "") + "$" + Math.abs(val).toFixed(2);
  }

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-blue-300/70 hover:text-blue-300 transition-colors underline underline-offset-2"
      >
        {expanded ? "Hide details" : `Show ${rides.length} affected routes`}
      </button>
      {expanded && (
        <div className="mt-2 rounded-lg overflow-x-auto bg-black/20 border border-white/5">
          <table className="w-full text-xs whitespace-nowrap">
            <thead>
              <tr className="text-left text-white/40 uppercase tracking-wide">
                <th className="px-3 py-1.5">Route</th>
                <th className="px-3 py-1.5 text-right">Partner Before</th>
                <th className="px-3 py-1.5 text-right">Partner Now</th>
                <th className="px-3 py-1.5 text-right">Partner &Delta;</th>
                <th className="px-3 py-1.5 text-right">Driver Before</th>
                <th className="px-3 py-1.5 text-right">Driver Now</th>
                <th className="px-3 py-1.5 text-right">Driver &Delta;</th>
                <th className="px-3 py-1.5 text-right">Margin &Delta;</th>
              </tr>
            </thead>
            <tbody>
              {rides.map((r, i) => (
                <tr key={i} className="border-t border-white/5">
                  <td className="px-3 py-1.5 text-white/70 truncate max-w-[200px]">
                    {r.route}
                  </td>
                  <td className="px-3 py-1.5 text-right text-white/50">
                    {formatCurrency(r.partner_before)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-white/70">
                    {formatCurrency(r.partner_now)}
                  </td>
                  <td className={`px-3 py-1.5 text-right ${deltaClass(r.partner_delta)}`}>
                    {formatDelta(r.partner_delta)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-white/50">
                    {formatCurrency(r.driver_before)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-white/70">
                    {formatCurrency(r.driver_now)}
                  </td>
                  <td className={`px-3 py-1.5 text-right ${deltaClass(r.driver_delta)}`}>
                    {formatDelta(r.driver_delta)}
                  </td>
                  <td className={`px-3 py-1.5 text-right ${marginDeltaClass(r.margin_delta)}`}>
                    {formatDelta(r.margin_delta)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Sibling route context (expandable) ───────────────────────────────────────

function SiblingRoutesDetail({
  siblings,
  groupIndex,
  onUseRate,
}: {
  siblings: SiblingRoute[];
  groupIndex: number;
  onUseRate: (rate: number) => void;
}) {
  // Auto-expand first 3 unpriced groups; collapse the rest by default
  const [expanded, setExpanded] = useState(groupIndex < 3);

  const kindLabel: Record<SiblingRoute["kind"], string> = {
    letter_variant: "Letter variant",
    numbered_neighbor: "Numbered neighbor",
    opposite_direction: "Opposite direction",
  };

  const kindClass: Record<SiblingRoute["kind"], string> = {
    letter_variant: "text-emerald-400/80 bg-emerald-400/10",
    numbered_neighbor: "text-white/40 bg-white/5",
    opposite_direction: "text-white/30 bg-white/5",
  };

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-white/30 hover:text-white/50 transition-colors underline underline-offset-2"
      >
        {expanded ? "Hide sibling routes" : "Compare to sibling routes"}
      </button>
      {expanded && (
        <div className="mt-2 rounded-lg overflow-hidden bg-black/20 border border-white/5">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-white/30 uppercase tracking-wide">
                <th className="px-3 py-1.5">Route</th>
                <th className="px-3 py-1.5">Match</th>
                <th className="px-3 py-1.5 text-right">Rate</th>
                <th className="px-3 py-1.5 text-right">Miles</th>
                <th className="px-3 py-1.5 text-right">Rides</th>
                <th className="px-3 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {siblings.map((s, i) => (
                <tr key={i} className="border-t border-white/5">
                  <td className="px-3 py-1.5 text-white/60 truncate max-w-[180px]">
                    {s.service_name}
                  </td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${kindClass[s.kind]}`}
                    >
                      {kindLabel[s.kind]}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-right text-white/70 font-medium">
                    {formatCurrency(s.current_rate)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-white/40">
                    {s.miles != null && s.miles > 0 ? `${s.miles} mi` : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right text-white/40">
                    {s.ride_count_30d > 0 ? s.ride_count_30d : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <button
                      onClick={() => onUseRate(s.current_rate)}
                      className="text-[10px] px-2 py-0.5 rounded bg-white/5 hover:bg-white/10 text-white/50 hover:text-white/80 transition-colors"
                    >
                      Use this rate
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Manual withhold button ────────────────────────────────────────────────────

function ManualWithholdButton({
  batchId,
  driver,
  onSaved,
}: {
  batchId: number;
  driver: PayrollDriver;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  async function withhold() {
    setSaving(true);
    try {
      await api.post(
        `/api/data/workflow/${batchId}/manual-withhold/${driver.id}`,
        { note },
      );
      onSaved();
      setOpen(false);
      setNote("");
    } finally {
      setSaving(false);
    }
  }

  async function release() {
    setSaving(true);
    try {
      await api.delete(
        `/api/data/workflow/${batchId}/manual-withhold/${driver.id}`,
      );
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  if (driver.manual_withhold_note != null) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-amber-400 font-semibold">
          Withheld
        </span>
        {driver.manual_withhold_note && (
          <span
            className="text-[10px] text-white/40 italic truncate max-w-[120px]"
            title={driver.manual_withhold_note}
          >
            "{driver.manual_withhold_note}"
          </span>
        )}
        <button
          onClick={release}
          disabled={saving}
          className="text-[10px] text-white/30 hover:text-red-400 transition-colors ml-1"
        >
          Release
        </button>
      </div>
    );
  }

  if (open) {
    return (
      <div className="flex items-center gap-1">
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") withhold();
            if (e.key === "Escape") setOpen(false);
          }}
          placeholder="Reason (optional)"
          autoFocus
          className="w-36 px-2 py-1 rounded text-xs text-white bg-white/10 border border-white/20 focus:border-amber-400 focus:outline-none"
        />
        <button
          onClick={withhold}
          disabled={saving}
          className="px-2 py-1 rounded text-xs bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 transition-colors disabled:opacity-50"
        >
          {saving ? "..." : "Withhold"}
        </button>
        <button
          onClick={() => setOpen(false)}
          className="text-xs text-white/30 hover:text-white/60"
        >
          ✕
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={() => setOpen(true)}
      className="text-[10px] text-white/20 hover:text-amber-400 transition-colors"
      title="Manually withhold this driver's pay"
    >
      Withhold
    </button>
  );
}

// ── Settle Externally button + modal ──────────────────────────────────────────

const EXTERNAL_METHOD_LABELS: Record<string, string> = {
  zelle: "Zelle",
  cash: "Cash",
  retained: "Retained",
  custom: "Custom",
};

function SettleExternalButton({
  batchId,
  driver,
  defaultAmount,
  onSaved,
}: {
  batchId: number;
  driver: PayrollDriver;
  defaultAmount: number;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState<"zelle" | "cash" | "retained" | "custom">("zelle");
  const [amount, setAmount] = useState(String(defaultAmount > 0 ? defaultAmount : ""));
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function settle() {
    const parsed = parseFloat(amount);
    if (isNaN(parsed) || parsed <= 0) {
      setError("Enter a valid amount");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.post(
        `/api/data/workflow/${batchId}/settle-external/${driver.id}`,
        { method, amount: parsed, note: note.trim() },
      );
      onSaved();
      setOpen(false);
      setNote("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to settle");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => {
          setAmount(String(defaultAmount > 0 ? defaultAmount : ""));
          setOpen(true);
        }}
        className="px-2.5 py-1 rounded-lg text-xs font-medium bg-violet-500/15 text-violet-400 hover:bg-violet-500/25 transition-colors"
        title="Mark this balance as settled outside Paychex"
      >
        Settle outside
      </button>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={() => setOpen(false)}
    >
      <div
        className="bg-[#1a1a2e] border border-white/10 rounded-xl p-5 w-80 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold text-white mb-1">
          Settle Outside — {driver.name}
        </h3>
        <p className="text-[11px] text-white/40 mb-4">
          This marks the balance as paid outside Paychex. The driver is excluded
          from the Paychex CSV and counts as paid in YTD.
        </p>

        {/* Method */}
        <label className="block text-[11px] text-white/50 mb-1">Method</label>
        <div className="grid grid-cols-4 gap-1 mb-4">
          {(["zelle", "cash", "retained", "custom"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMethod(m)}
              className={`py-1.5 rounded text-[11px] font-medium transition-colors ${
                method === m
                  ? "bg-violet-500/30 text-violet-300 border border-violet-500/50"
                  : "bg-white/5 text-white/40 hover:bg-white/10 border border-white/10"
              }`}
            >
              {EXTERNAL_METHOD_LABELS[m]}
            </button>
          ))}
        </div>

        {/* Amount */}
        <label className="block text-[11px] text-white/50 mb-1">Amount ($)</label>
        <input
          type="number"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          min="0"
          step="0.01"
          className="w-full px-3 py-2 rounded-lg text-sm text-white bg-white/10 border border-white/20 focus:border-violet-400 focus:outline-none mb-3"
        />

        {/* Note */}
        <label className="block text-[11px] text-white/50 mb-1">Note (optional)</label>
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") settle(); if (e.key === "Escape") setOpen(false); }}
          placeholder="e.g. paid via Zelle by mom"
          className="w-full px-3 py-2 rounded-lg text-sm text-white bg-white/10 border border-white/20 focus:border-violet-400 focus:outline-none mb-4"
        />

        {error && (
          <p className="text-[11px] text-red-400 mb-3">{error}</p>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={settle}
            disabled={saving}
            className="flex-1 py-2 rounded-lg text-sm font-medium bg-violet-500/20 text-violet-300 hover:bg-violet-500/30 transition-colors disabled:opacity-50"
          >
            {saving ? "Saving..." : "Confirm"}
          </button>
          <button
            onClick={() => setOpen(false)}
            className="px-4 py-2 rounded-lg text-sm text-white/40 hover:text-white/60 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Click-to-edit cell ────────────────────────────────────────────────────────

function ClickToEdit({
  value,
  placeholder,
  inputType = "text",
  onSave,
}: {
  value: string;
  placeholder: string;
  inputType?: string;
  onSave: (val: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(value);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Keep in sync if parent data refreshes
  useEffect(() => {
    if (!editing) setVal(value);
  }, [value, editing]);

  async function commit() {
    if (val.trim() === value) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(val.trim());
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  if (editing) {
    return (
      <input
        autoFocus
        type={inputType}
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") setEditing(false);
        }}
        className="w-full px-2 py-1 rounded-lg text-xs text-white bg-white/10 border border-[#667eea] focus:outline-none"
      />
    );
  }

  return (
    <button
      onClick={() => setEditing(true)}
      className={`text-xs px-1 py-0.5 rounded hover:bg-white/10 transition-colors text-left w-full group ${saved ? "text-emerald-400" : val ? "text-white/70" : "text-white/25 italic"}`}
    >
      {saved ? "✓ Saved" : val || placeholder}
      {!saved && (
        <Pencil className="w-2.5 h-2.5 inline ml-1 opacity-0 group-hover:opacity-60 transition-opacity" />
      )}
      {saving && <Loader2 className="w-2.5 h-2.5 inline ml-1 animate-spin" />}
    </button>
  );
}

// ── Inline editors for warnings ─────────────────────────────────────────────

function InlinePayCodeEditor({
  batchId,
  affected,
  onSaved,
}: {
  batchId: number;
  affected: AffectedPerson[];
  onSaved: () => void;
}) {
  const [values, setValues] = useState<Record<number, string>>(() => {
    const m: Record<number, string> = {};
    affected.forEach((p) => {
      m[p.person_id] = p.paycheck_code || "";
    });
    return m;
  });
  const [saving, setSaving] = useState<number | null>(null);
  const [saved, setSaved] = useState<Set<number>>(new Set());
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const [errors, setErrors] = useState<Record<number, string>>({});

  // Keep values in sync when the parent re-fetches (e.g. after save or
  // navigation back).  Only overwrite entries that are NOT currently mid-save
  // so live input is never clobbered.  Mirrors ClickToEdit's useEffect pattern
  // so the pre-fill always reflects the latest DB value on re-mount.
  useEffect(() => {
    setValues((prev) => {
      const next = { ...prev };
      affected.forEach((p) => {
        if (saving !== p.person_id) {
          next[p.person_id] = p.paycheck_code || "";
        }
      });
      return next;
    });
  }, [affected, saving]);

  async function save(personId: number) {
    const code = values[personId]?.trim();
    if (!code) return;
    setSaving(personId);
    setErrors((prev) => {
      const e = { ...prev };
      delete e[personId];
      return e;
    });
    try {
      await api.patch(
        `/api/data/workflow/${batchId}/update-person/${personId}`,
        { paycheck_code: code },
      );
      setSaved((prev) => new Set(prev).add(personId));
      onSaved();
    } catch (e) {
      setErrors((prev) => ({ ...prev, [personId]: "Save failed" }));
    } finally {
      setSaving(null);
    }
  }

  const visible = affected.filter((p) => !skipped.has(p.person_id));
  if (visible.length === 0)
    return (
      <p className="mt-2 text-xs text-white/40 italic">
        All skipped — you can still approve payroll.
      </p>
    );

  return (
    <div className="mt-3 space-y-2">
      {visible.map((p) => (
        <div
          key={p.person_id}
          className="flex items-center gap-2 bg-black/20 rounded-lg px-3 py-2"
        >
          <span className="text-sm text-white/80 flex-1 min-w-0 truncate">
            {p.name}
          </span>
          {saved.has(p.person_id) ? (
            <span className="text-sm text-emerald-400 inline-flex items-center gap-1.5 font-medium">
              <Check className="w-4 h-4" /> Saved
            </span>
          ) : (
            <>
              {errors[p.person_id] && (
                <span className="text-xs text-red-400">
                  {errors[p.person_id]}
                </span>
              )}
              <input
                type="text"
                value={values[p.person_id] || ""}
                onChange={(e) =>
                  setValues((prev) => ({
                    ...prev,
                    [p.person_id]: e.target.value,
                  }))
                }
                onKeyDown={(e) => e.key === "Enter" && save(p.person_id)}
                placeholder="Paychex code"
                className="w-32 px-2.5 py-1.5 rounded-lg text-sm text-white bg-white/10 border border-white/20 focus:border-amber-400 focus:outline-none"
              />
              <button
                onClick={() => save(p.person_id)}
                disabled={
                  saving === p.person_id || !values[p.person_id]?.trim()
                }
                className="px-3 py-1.5 rounded-lg text-sm font-medium bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 disabled:opacity-40 transition-colors inline-flex items-center gap-1.5"
              >
                {saving === p.person_id ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Save className="w-3.5 h-3.5" />
                )}
                Save
              </button>
              <button
                onClick={() =>
                  setSkipped((prev) => new Set(prev).add(p.person_id))
                }
                className="px-2 py-1.5 rounded-lg text-xs text-white/30 hover:text-white/60 transition-colors"
              >
                Skip
              </button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function InlineEmailEditor({
  batchId,
  affected,
  onSaved,
}: {
  batchId: number;
  affected: AffectedPerson[];
  onSaved: () => void;
}) {
  const [values, setValues] = useState<Record<number, string>>(() => {
    const m: Record<number, string> = {};
    affected.forEach((p) => {
      m[p.person_id] = p.email || "";
    });
    return m;
  });
  const [saving, setSaving] = useState<number | null>(null);
  const [saved, setSaved] = useState<Set<number>>(new Set());
  const [errors, setErrors] = useState<Record<number, string>>({});

  async function save(personId: number) {
    const email = values[personId]?.trim();
    if (!email) return;
    setSaving(personId);
    setErrors((prev) => {
      const e = { ...prev };
      delete e[personId];
      return e;
    });
    try {
      await api.patch(
        `/api/data/workflow/${batchId}/update-person/${personId}`,
        { email },
      );
      setSaved((prev) => new Set(prev).add(personId));
      onSaved();
    } catch (e) {
      setErrors((prev) => ({ ...prev, [personId]: "Save failed" }));
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="mt-3 space-y-2">
      {affected.map((p) => (
        <div
          key={p.person_id}
          className="flex items-center gap-2 bg-black/20 rounded-lg px-3 py-2"
        >
          <span className="text-sm text-white/80 flex-1 min-w-0 truncate">
            {p.name}
          </span>
          {saved.has(p.person_id) ? (
            <span className="text-sm text-emerald-400 inline-flex items-center gap-1.5 font-medium">
              <Check className="w-4 h-4" /> Saved
            </span>
          ) : (
            <>
              {errors[p.person_id] && (
                <span className="text-xs text-red-400">
                  {errors[p.person_id]}
                </span>
              )}
              <input
                type="email"
                value={values[p.person_id] || ""}
                onChange={(e) =>
                  setValues((prev) => ({
                    ...prev,
                    [p.person_id]: e.target.value,
                  }))
                }
                onKeyDown={(e) => e.key === "Enter" && save(p.person_id)}
                placeholder="email@example.com"
                className="w-48 px-2.5 py-1.5 rounded-lg text-sm text-white bg-white/10 border border-white/20 focus:border-blue-400 focus:outline-none"
              />
              <button
                onClick={() => save(p.person_id)}
                disabled={
                  saving === p.person_id || !values[p.person_id]?.trim()
                }
                className="px-3 py-1.5 rounded-lg text-sm font-medium bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 disabled:opacity-40 transition-colors inline-flex items-center gap-1.5"
              >
                {saving === p.person_id ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Save className="w-3.5 h-3.5" />
                )}
                Save
              </button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function InlineRateEditor({
  batchId,
  affected,
  onSaved,
}: {
  batchId: number;
  affected: NegativeMarginDetail[];
  onSaved: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const m: Record<string, string> = {};
    affected.forEach((r) => {
      m[r.service_name] = r.z_rate.toString();
    });
    return m;
  });
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  // Per-ride single-override state (keyed by ride_id)
  const [savingRide, setSavingRide] = useState<number | null>(null);
  const [savedRides, setSavedRides] = useState<Set<number>>(new Set());
  const [rideErrors, setRideErrors] = useState<Record<number, string>>({});
  // Per-ride "Keep for company" soft-delete state
  const [removingRide, setRemovingRide] = useState<number | null>(null);
  const [removedRides, setRemovedRides] = useState<Set<number>>(new Set());

  async function save(
    serviceName: string,
    mode: "default" | "late_cancellation" | "batch_only" = "default",
  ) {
    const rate = parseFloat(values[serviceName] || "");
    if (isNaN(rate) || rate < 0) return;
    setSaving(serviceName);
    setErrors((prev) => {
      const e = { ...prev };
      delete e[serviceName];
      return e;
    });
    try {
      await api.patch(`/api/data/workflow/${batchId}/update-ride-rate`, {
        service_name: serviceName,
        z_rate: rate,
        mode,
      });
      setSaved((prev) => new Set(prev).add(serviceName));
      onSaved();
    } catch (e) {
      setErrors((prev) => ({ ...prev, [serviceName]: "Save failed" }));
    } finally {
      setSaving(null);
    }
  }

  // Single-ride override — sets z_rate on exactly one ride by ride_id.
  // Does NOT touch other rides on the same route.
  async function saveOneRide(rideId: number, serviceName: string) {
    const rate = parseFloat(values[serviceName] || "");
    if (isNaN(rate) || rate < 0) return;
    setSavingRide(rideId);
    setRideErrors((prev) => { const e = { ...prev }; delete e[rideId]; return e; });
    try {
      await api.patch(`/api/data/workflow/${batchId}/update-ride-rate`, {
        ride_id: rideId,
        z_rate: rate,
        mode: "single_ride",
      });
      setSavedRides((prev) => new Set(prev).add(rideId));
      onSaved();
    } catch {
      setRideErrors((prev) => ({ ...prev, [rideId]: "Save failed" }));
    } finally {
      setSavingRide(null);
    }
  }

  // Soft-delete a ride — money belongs to company, not driver
  async function keepForCompany(rideId: number) {
    setRemovingRide(rideId);
    try {
      await api.patch(`/api/data/rides/${rideId}/remove`, {
        reason: "FA pay correction — money belongs to company per Malik",
      });
      setRemovedRides((prev) => new Set(prev).add(rideId));
      onSaved();
    } catch {
      // Surface inline — don't block other actions
    } finally {
      setRemovingRide(null);
    }
  }

  // Detect which affected rows look like late cancellations (net_pay is 40–55% of z_rate).
  function isLateCancel(r: NegativeMarginDetail): boolean {
    if (!r.z_rate || !r.net_pay) return false;
    const ratio = r.net_pay / r.z_rate;
    return ratio >= 0.4 && ratio <= 0.55;
  }

  return (
    <div className="mt-3 rounded-lg overflow-hidden bg-black/20 border border-white/10">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-white/40 text-xs uppercase border-b border-white/10">
            <th className="px-3 py-2">Driver · Route</th>
            <th className="px-3 py-2 text-right">Rides</th>
            <th className="px-3 py-2 text-right">Co. Rate</th>
            <th className="px-3 py-2 text-right">Driver Rate</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {affected
            .filter((r) => !dismissed.has(r.service_name))
            .map((r, i) => (
              <Fragment key={i}>
              <tr className="border-t border-white/5">
                <td className="px-3 py-2 max-w-[220px]">
                  {r.drivers && r.drivers.length > 0 && (
                    <div className="text-white font-medium text-xs mb-0.5 truncate">
                      {r.drivers.join(", ")}
                    </div>
                  )}
                  <div className="text-white/50 text-xs truncate">{r.service_name}</div>
                </td>
                <td className="px-3 py-2 text-right text-white/50">
                  {r.count}
                </td>
                <td className="px-3 py-2 text-right text-white/50">
                  {formatCurrency(r.net_pay)}
                </td>
                <td className="px-3 py-2 text-right">
                  {saved.has(r.service_name) ? (
                    <span className="text-emerald-400 inline-flex items-center gap-1 font-medium">
                      <Check className="w-3.5 h-3.5" />{" "}
                      {formatCurrency(
                        parseFloat(values[r.service_name] || "0"),
                      )}
                    </span>
                  ) : (
                    <div className="inline-flex items-center gap-1">
                      <span className="text-white/40">$</span>
                      <input
                        type="number"
                        step="1"
                        min="0"
                        value={values[r.service_name] || ""}
                        onChange={(e) =>
                          setValues((prev) => ({
                            ...prev,
                            [r.service_name]: e.target.value,
                          }))
                        }
                        onKeyDown={(e) =>
                          e.key === "Enter" && save(r.service_name)
                        }
                        className="w-20 px-2 py-1 rounded-lg text-sm text-white bg-white/10 border border-white/20 focus:border-amber-400 focus:outline-none text-right"
                      />
                      {errors[r.service_name] && (
                        <span className="text-xs text-red-400 ml-1">
                          {errors[r.service_name]}
                        </span>
                      )}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {!saved.has(r.service_name) && (
                    <div className="inline-flex items-center gap-2 flex-wrap justify-end">
                      <button
                        onClick={() => save(r.service_name, "default")}
                        disabled={
                          saving === r.service_name || !values[r.service_name]
                        }
                        className="px-3 py-1 rounded-lg text-sm font-medium bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 disabled:opacity-40 transition-colors inline-flex items-center gap-1.5 whitespace-nowrap"
                        title="Saves this as the permanent rate for this route — applies to all future batches too"
                      >
                        {saving === r.service_name ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Save className="w-3.5 h-3.5" />
                        )}
                        Save rate (all batches)
                      </button>
                      {isLateCancel(r) && (
                        <button
                          onClick={() =>
                            save(r.service_name, "late_cancellation")
                          }
                          disabled={
                            saving === r.service_name || !values[r.service_name]
                          }
                          className="px-3 py-1 rounded-lg text-xs font-medium bg-purple-500/15 text-purple-300 hover:bg-purple-500/25 disabled:opacity-40 transition-colors inline-flex items-center gap-1.5 whitespace-nowrap"
                          title="Sets the late-cancellation rate for this route — applies to ALL late-cancel rides on this route in this batch (net_pay 40–55% of default). Regular rides keep their rate. Future batches use this as the auto late-cancel rate."
                        >
                          Late-cancel rate (all matching rides)
                        </button>
                      )}
                      <button
                        onClick={() => save(r.service_name, "batch_only")}
                        disabled={
                          saving === r.service_name || !values[r.service_name]
                        }
                        className="px-3 py-1 rounded-lg text-xs font-medium bg-cyan-500/15 text-cyan-300 hover:bg-cyan-500/25 disabled:opacity-40 transition-colors inline-flex items-center gap-1.5 whitespace-nowrap"
                        title="Sets rate for ALL rides on this route in this batch only — permanent rate stays unchanged. Use if every ride on this route needs a one-time correction."
                      >
                        Apply to this batch only
                      </button>
                      <button
                        onClick={() =>
                          setDismissed((prev) =>
                            new Set(prev).add(r.service_name),
                          )
                        }
                        className="px-2 py-1 rounded-lg text-xs text-white/30 hover:text-white/60 transition-colors whitespace-nowrap"
                        title="Dismiss — the driver rate is intentionally set this way"
                      >
                        Skip — rate is correct
                      </button>
                    </div>
                  )}
                </td>
              </tr>
              {/* Per-ride sub-rows — single-ride overrides and "Keep for company" removal.
                  Shown when backend provides individual ride data.
                  This prevents a route-level blast when only one specific ride
                  needs a rate change (e.g., a one-off late cancellation). */}
              {!saved.has(r.service_name) && r.rides && r.rides.length > 0 && (
                <tr className="border-t border-white/5 bg-black/10">
                  <td colSpan={5} className="px-3 py-2">
                    <div className="text-white/30 text-xs mb-1.5 font-medium uppercase tracking-wide">
                      ↳ Per-ride actions (safe — each action targets only this one ride)
                    </div>
                    <div className="flex flex-col gap-1">
                      {r.rides.map((ride) => {
                        const isRemoved = removedRides.has(ride.ride_id);
                        return (
                          <div key={ride.ride_id} className="flex items-center gap-2 text-xs">
                            <span className="text-white/40 w-20 shrink-0">{ride.ride_date ?? "—"}</span>
                            <span className="text-white/60 truncate max-w-[140px]">{ride.driver}</span>
                            <span className="text-white/30 ml-auto shrink-0">was {formatCurrency(ride.z_rate)}</span>
                            {isRemoved ? (
                              <span className="text-red-400/70 inline-flex items-center gap-1 shrink-0 text-[10px] font-medium uppercase tracking-wide">
                                <X className="w-3 h-3" />
                                Kept for company
                              </span>
                            ) : savedRides.has(ride.ride_id) ? (
                              <span className="text-emerald-400 inline-flex items-center gap-1 shrink-0">
                                <Check className="w-3 h-3" />
                                {formatCurrency(parseFloat(values[r.service_name] || "0"))}
                              </span>
                            ) : (
                              <>
                                <button
                                  onClick={() => saveOneRide(ride.ride_id, r.service_name)}
                                  disabled={savingRide === ride.ride_id || removingRide === ride.ride_id || !values[r.service_name]}
                                  className="px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-40 transition-colors inline-flex items-center gap-1 shrink-0"
                                  title="Set this rate on this one ride only — all other rides on this route are untouched"
                                >
                                  {savingRide === ride.ride_id ? (
                                    <Loader2 className="w-3 h-3 animate-spin" />
                                  ) : (
                                    <Save className="w-3 h-3" />
                                  )}
                                  Override this ride only
                                </button>
                                <button
                                  onClick={() => keepForCompany(ride.ride_id)}
                                  disabled={removingRide === ride.ride_id || savingRide === ride.ride_id}
                                  className="px-2 py-0.5 rounded text-xs font-medium bg-red-500/15 text-red-400 hover:bg-red-500/25 disabled:opacity-40 transition-colors inline-flex items-center gap-1 shrink-0 whitespace-nowrap"
                                  title="Remove this ride from driver payout — money stays with company. Use for FA back-pay lines that were already paid."
                                >
                                  {removingRide === ride.ride_id ? (
                                    <Loader2 className="w-3 h-3 animate-spin" />
                                  ) : (
                                    <X className="w-3 h-3" />
                                  )}
                                  Keep for company
                                </button>
                                {rideErrors[ride.ride_id] && (
                                  <span className="text-red-400">{rideErrors[ride.ride_id]}</span>
                                )}
                              </>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Step 2: Payroll Review ──────────────────────────────────────────────────

function PayrollReviewStep({
  batchId,
  status,
  onAdvance,
  advancing,
  onRefresh,
  isAdmin,
  onReopen,
  onGoBack,
}: {
  batchId: number;
  status: BatchStatus;
  onAdvance: (force?: boolean) => void;
  advancing: boolean;
  onRefresh: () => Promise<void>;
  isAdmin?: boolean;
  onReopen?: () => Promise<void>;
  onGoBack?: () => Promise<void>;
}) {
  const router = useRouter();
  const [data, setData] = useState<PayrollPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [showConfirm, setShowConfirm] = useState(false);
  const [locking, setLocking] = useState(false);
  const [lockError, setLockError] = useState<string | null>(null);

  const reloadPreview = useCallback(() => {
    return api
      .get<PayrollPreview>(`/api/data/workflow/${batchId}/payroll-preview`)
      .then(setData)
      .catch((e) => { console.error(e); toast.error('Failed to load payroll preview') });
  }, [batchId]);

  useEffect(() => {
    reloadPreview().finally(() => setLoading(false));
  }, [reloadPreview]);

  async function handleInlineRefresh() {
    await reloadPreview();
    await onRefresh();
  }

  async function handleLockAndApprove() {
    setLocking(true);
    setLockError(null);
    try {
      await api.post(`/api/data/workflow/${batchId}/lock-and-approve`, {});
      await onRefresh();
      setShowConfirm(false);
    } catch (e: unknown) {
      let msg = e instanceof Error ? e.message : "Failed to approve payroll";
      try {
        const parsed = JSON.parse(msg);
        if (parsed?.blockers?.length) msg = parsed.blockers.join(" · ");
        else if (parsed?.error) msg = parsed.error;
      } catch {
        /* plain string */
      }
      setLockError(msg);
    } finally {
      setLocking(false);
    }
  }

  if (loading) return <LoadingSpinner />;
  if (!data) return null;

  const { drivers, withheld, totals, warnings, stats } = data;

  return (
    <div>
      <h2 className="text-lg font-semibold text-white mb-4">Payroll Review</h2>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="space-y-2 mb-4">
          {warnings.map((w, i) => (
            <AlertCard
              key={i}
              severity={w.severity}
              title={w.title}
              description={w.description}
              action={
                w.type === "missing_pay_code" && w.affected?.length ? (
                  <InlinePayCodeEditor
                    batchId={batchId}
                    affected={w.affected as AffectedPerson[]}
                    onSaved={handleInlineRefresh}
                  />
                ) : w.type === "missing_email" && w.affected?.length ? (
                  <InlineEmailEditor
                    batchId={batchId}
                    affected={w.affected as AffectedPerson[]}
                    onSaved={handleInlineRefresh}
                  />
                ) : w.type === "negative_margin" && w.affected?.length ? (
                  <InlineRateEditor
                    batchId={batchId}
                    affected={w.affected as NegativeMarginDetail[]}
                    onSaved={handleInlineRefresh}
                  />
                ) : w.type === "late_cancellation" && w.rides?.length ? (
                  <LateCancellationDetail batchId={batchId} rides={w.rides as LateCancelRide[]} onSaved={handleInlineRefresh} />
                ) : w.type === "net_pay_change" && w.rides?.length ? (
                  <NetPayChangeDetail rides={w.rides as NetPayChangeRide[]} />
                ) : undefined
              }
            />
          ))}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
        <StatCard
          label="Drivers"
          value={stats.driver_count}
          icon={<Users className="w-4 h-4" />}
          index={0}
        />
        <StatCard
          label="Total Payout"
          value={formatCurrency(stats.total_pay)}
          icon={<DollarSign className="w-4 h-4" />}
          color="success"
          index={1}
        />
        <StatCard
          label="Withheld"
          value={formatCurrency(stats.withheld_amount)}
          icon={<AlertTriangle className="w-4 h-4" />}
          color="warning"
          index={2}
        />
        <StatCard
          label="Under $100"
          value={stats.withheld_count}
          icon={<Package className="w-4 h-4" />}
          color="danger"
          index={3}
        />
        {(stats.settled_externally_count ?? 0) > 0 && (
          <StatCard
            label="Settled Outside"
            value={formatCurrency(stats.settled_externally_amount ?? 0)}
            icon={<DollarSign className="w-4 h-4" />}
            color="default"
            index={4}
          />
        )}
      </div>

      {/* Paid drivers table — columns match mom's Excel order:
           Driver Name | Pay Code | Rides | Miles | Partner Pays | Driver Pay |
           Deduction | Carried Over | Paid This Period | Email (edit) | Actions  */}
      <div className="rounded-xl overflow-hidden dark:bg-white/5 dark:border dark:border-white/10 mb-4">
        <div className="px-4 py-2.5 border-b border-white/10">
          <span className="text-sm font-medium text-white">
            Paid This Period ({drivers.length})
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-white/40 text-xs uppercase">
                <th className="px-4 py-2.5">Driver Name</th>
                <th className="px-4 py-2.5 text-center">Pay Code</th>
                <th className="px-4 py-2.5 text-right">Rides</th>
                <th className="px-4 py-2.5 text-right">Miles</th>
                <th className="px-4 py-2.5 text-right">Partner Pays</th>
                <th className="px-4 py-2.5 text-right">Driver Pay</th>
                <th className="px-4 py-2.5 text-right">Deduction</th>
                <th className="px-4 py-2.5 text-right">Carried Forward</th>
                <th className="px-4 py-2.5 text-right">Paid This Period</th>
                <th className="px-4 py-2.5">Email</th>
                <th className="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {drivers.map((d) => (
                <tr
                  key={d.id}
                  className="border-t border-white/5 hover:bg-white/5 transition-colors cursor-pointer"
                  onClick={() =>
                    router.push(`/payroll/history/${batchId}/driver/${d.id}`)
                  }
                >
                  <td className="px-4 py-2">
                    <a
                      href={`/payroll/history/${batchId}/driver/${d.id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-white hover:text-[#667eea] hover:underline transition-colors"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {d.name}
                    </a>
                  </td>
                  <td
                    className="px-4 py-2 text-center"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <ClickToEdit
                      value={d.pay_code || ""}
                      placeholder="Add code"
                      onSave={(val) =>
                        api
                          .patch(
                            `/api/data/workflow/${batchId}/update-person/${d.id}`,
                            { paycheck_code: val },
                          )
                          .then(handleInlineRefresh)
                      }
                    />
                  </td>
                  <td className="px-4 py-2 text-right text-white/60">
                    {d.rides}
                  </td>
                  <td className="px-4 py-2 text-right text-white/60">
                    {d.miles ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-white/60">
                    {formatCurrency(d.partner_pays ?? d.net_pay)}
                  </td>
                  <td className="px-4 py-2 text-right text-white/60">
                    {formatCurrency(d.driver_pay ?? d.net_pay)}
                  </td>
                  <td className="px-4 py-2 text-right text-white/60">
                    {d.deduction ? formatCurrency(d.deduction) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-white/60">
                    {(d.withheld_amount ?? 0) > 0 ? formatCurrency(d.withheld_amount) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-emerald-400 font-medium">
                    {formatCurrency(d.pay_this_period)}
                  </td>
                  <td
                    className="px-4 py-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <ClickToEdit
                      value={d.email || ""}
                      placeholder="Add email"
                      inputType="email"
                      onSave={(val) =>
                        api
                          .patch(
                            `/api/data/workflow/${batchId}/update-person/${d.id}`,
                            { email: val },
                          )
                          .then(handleInlineRefresh)
                      }
                    />
                  </td>
                  <td
                    className="px-4 py-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="flex items-center gap-0.5">
                      <ManualWithholdButton
                        batchId={batchId}
                        driver={d}
                        onSaved={handleInlineRefresh}
                      />
                      <AddAdjustmentButton
                        batchId={batchId}
                        batchSource={status.source}
                        batchCompanyIsMaz={isBatchMaz(status)}
                        driver={d}
                        onSaved={handleInlineRefresh}
                      />
                      <ViewAdjustmentsButton
                        batchId={batchId}
                        driver={d}
                        onDeleted={handleInlineRefresh}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-white/20 font-bold">
                <td className="px-4 py-2.5 text-white" colSpan={2}>
                  TOTALS
                </td>
                <td className="px-4 py-2.5 text-right text-white">
                  {totals.rides ?? ""}
                </td>
                <td className="px-4 py-2.5 text-right text-white">
                  {totals.miles != null ? totals.miles : ""}
                </td>
                <td className="px-4 py-2.5 text-right text-white">
                  {formatCurrency(totals.net_pay)}
                </td>
                <td className="px-4 py-2.5 text-right text-white">
                  {formatCurrency(totals.net_pay)}
                </td>
                <td className="px-4 py-2.5"></td>
                <td className="px-4 py-2.5"></td>
                <td className="px-4 py-2.5 text-right text-emerald-400">
                  {formatCurrency(totals.pay_this_period)}
                </td>
                <td colSpan={2}></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* Withheld section */}
      {withheld.length > 0 && (
        <div className="rounded-xl overflow-hidden dark:bg-white/5 dark:border dark:border-white/10 mb-6">
          <div className="px-4 py-2.5 border-b border-white/10">
            <span className="text-sm font-medium text-amber-400">
              Withheld — Under $100 ({withheld.length})
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-white/40 text-xs uppercase">
                  <th className="px-4 py-2.5">Driver Name</th>
                  <th className="px-4 py-2.5 text-center">Pay Code</th>
                  <th className="px-4 py-2.5 text-right">Rides</th>
                  <th className="px-4 py-2.5 text-right">Driver Pay</th>
                  <th className="px-4 py-2.5 text-right">Carried Over</th>
                  <th className="px-4 py-2.5 text-right">Withheld Balance</th>
                  <th className="px-4 py-2.5">Email</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {withheld.map((d) => (
                  <tr
                    key={d.id}
                    className="border-t border-white/5 hover:bg-white/5 transition-colors cursor-pointer"
                    onClick={() =>
                      router.push(`/payroll/history/${batchId}/driver/${d.id}`)
                    }
                  >
                    <td className="px-4 py-2 text-white">
                      {d.name}
                      {d.force_pay_override && (
                        <span className="ml-2 text-[10px] text-emerald-400 font-semibold uppercase">
                          Force pay
                        </span>
                      )}
                      {d.manual_withhold_note != null && (
                        <span className="ml-2 text-[10px] text-amber-400 font-semibold uppercase">
                          Manual hold
                        </span>
                      )}
                      {d.missing_paycheck_code && (
                        <span className="ml-2 text-[10px] text-rose-400 font-semibold uppercase">
                          No Paychex code
                        </span>
                      )}
                      {d.manual_withhold_note && (
                        <span className="ml-1 text-[10px] text-white/30 italic">
                          "{d.manual_withhold_note}"
                        </span>
                      )}
                      {(() => {
                        const firstName = d.name.split(" ")[0];
                        const carried = d.carried_over ?? 0;
                        const hasRides = (d.rides ?? 0) > 0;
                        const src = d.balance_source;
                        const weekLabel = src ? balanceWeekLabel(src) : "a previous week";
                        let desc = "";
                        if (carried > 0 && !hasRides) {
                          // Pure carry-forward — no rides this week
                          desc = `All of this ${formatCurrency(d.withheld_amount)} has been waiting since ${weekLabel}. Make sure ${firstName} wasn't already paid another way before sending it.`;
                        } else if (carried > 0 && hasRides) {
                          // Mix: carry + new rides
                          const thisWeek = d.net_pay ?? 0;
                          desc = `${formatCurrency(carried)} carried over from ${weekLabel} plus ${formatCurrency(thisWeek)} from this week. Still under $100, so it'll keep waiting.`;
                        } else if (!carried && hasRides) {
                          // New this week only
                          desc = `Just from this week's rides. Under $100, so it'll save up for next week.`;
                        } else {
                          // No rides, no carry
                          desc = `Holding — nothing this week.`;
                        }
                        return (
                          <div className="mt-0.5 text-[11px] text-white/40">
                            {desc}
                          </div>
                        );
                      })()}
                    </td>
                    <td
                      className="px-4 py-2 text-center"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <ClickToEdit
                        value={d.pay_code || ""}
                        placeholder="Add code"
                        onSave={(val) =>
                          api
                            .patch(
                              `/api/data/workflow/${batchId}/update-person/${d.id}`,
                              { paycheck_code: val },
                            )
                            .then(handleInlineRefresh)
                        }
                      />
                    </td>
                    <td className="px-4 py-2 text-right text-white/60">
                      {d.rides ?? "—"}
                    </td>
                    <td className="px-4 py-2 text-right text-white/60">
                      {formatCurrency(d.driver_pay ?? d.net_pay)}
                    </td>
                    <td className="px-4 py-2 text-right text-white/60">
                      {d.carried_over ? formatCurrency(d.carried_over) : "—"}
                    </td>
                    <td className="px-4 py-2 text-right text-amber-400">
                      {formatCurrency(d.withheld_amount)}
                    </td>
                    <td
                      className="px-4 py-2"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <ClickToEdit
                        value={d.email || ""}
                        placeholder="Add email"
                        inputType="email"
                        onSave={(val) =>
                          api
                            .patch(
                              `/api/data/workflow/${batchId}/update-person/${d.id}`,
                              { email: val },
                            )
                            .then(handleInlineRefresh)
                        }
                      />
                    </td>
                    <td
                      className="px-4 py-2 text-right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center justify-end gap-1 flex-wrap">
                        {d.force_pay_override ? (
                          <button
                            onClick={() =>
                              api
                                .delete(
                                  `/api/data/workflow/${batchId}/override-withheld/${d.id}`,
                                )
                                .then(handleInlineRefresh)
                            }
                            className="text-xs text-white/30 hover:text-red-400 transition-colors"
                          >
                            Undo
                          </button>
                        ) : (
                          <button
                            onClick={() =>
                              api
                                .post(
                                  `/api/data/workflow/${batchId}/override-withheld/${d.id}`,
                                  {},
                                )
                                .then(handleInlineRefresh)
                            }
                            className="px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors"
                          >
                            Force pay
                          </button>
                        )}
                        {d.manual_withhold_note != null && (
                          <button
                            onClick={() =>
                              api
                                .delete(
                                  `/api/data/workflow/${batchId}/manual-withhold/${d.id}`,
                                )
                                .then(handleInlineRefresh)
                            }
                            className="ml-1 text-xs text-amber-400 hover:text-white/60 transition-colors"
                          >
                            Release hold
                          </button>
                        )}
                        <SettleExternalButton
                          batchId={batchId}
                          driver={d}
                          defaultAmount={d.withheld_amount ?? 0}
                          onSaved={handleInlineRefresh}
                        />
                        <AddAdjustmentButton
                          batchId={batchId}
                          batchSource={status.source}
                          batchCompanyIsMaz={isBatchMaz(status)}
                          driver={d}
                          onSaved={handleInlineRefresh}
                        />
                        <ViewAdjustmentsButton
                          batchId={batchId}
                          driver={d}
                          onDeleted={handleInlineRefresh}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Paid Externally panel */}
      {(data.settled_externally ?? []).length > 0 && (
        <div className="rounded-xl overflow-hidden dark:bg-white/5 dark:border dark:border-white/10 mb-6">
          <div className="px-4 py-2.5 border-b border-white/10">
            <span className="text-sm font-medium text-violet-400">
              Paid Externally ({(data.settled_externally ?? []).length})
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-white/40 text-xs uppercase">
                  <th className="px-4 py-2.5">Driver Name</th>
                  <th className="px-4 py-2.5 text-center">Method</th>
                  <th className="px-4 py-2.5 text-right">Amount Settled</th>
                  <th className="px-4 py-2.5">Note</th>
                  <th className="px-4 py-2.5 text-right">Settled At</th>
                </tr>
              </thead>
              <tbody>
                {(data.settled_externally ?? []).map((d) => (
                  <tr
                    key={d.id}
                    className="border-t border-white/5 hover:bg-white/5 transition-colors"
                  >
                    <td className="px-4 py-2 text-white">
                      {d.name}
                      <span className="ml-2 text-[10px] text-violet-400 font-semibold uppercase">
                        Paid externally
                      </span>
                    </td>
                    <td className="px-4 py-2 text-center">
                      <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-violet-500/15 text-violet-300 uppercase">
                        {EXTERNAL_METHOD_LABELS[d.external_method ?? ""] ?? d.external_method ?? "—"}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right text-violet-300 font-medium">
                      {d.external_amount != null ? formatCurrency(d.external_amount) : "—"}
                    </td>
                    <td className="px-4 py-2 text-white/50 text-xs italic">
                      {d.external_note ?? "—"}
                    </td>
                    <td className="px-4 py-2 text-right text-white/40 text-xs">
                      {d.settled_at ? new Date(d.settled_at).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Late-cancel and other gate warnings */}
      {(status.warnings ?? []).length > 0 && (
        <div className="space-y-2 mb-4">
          {(status.warnings ?? []).map((w, i) => (
            <div
              key={i}
              className="flex items-start gap-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/30"
            >
              <span className="text-amber-400 text-sm mt-0.5">⚠</span>
              <p className="text-sm text-amber-300">{w}</p>
            </div>
          ))}
        </div>
      )}

      {/* Lock & Approve */}
      {lockError && (
        <div className="mb-3 px-4 py-2.5 rounded-xl bg-red-500/15 border border-red-500/30 text-red-300 text-sm">
          {lockError}
        </div>
      )}
      {!showConfirm ? (
        <div className="text-center">
          <button
            onClick={() => setShowConfirm(true)}
            className="px-6 py-2.5 rounded-xl bg-emerald-600 text-white font-medium hover:bg-emerald-500 transition-colors inline-flex items-center gap-2"
          >
            <Check className="w-4 h-4" />
            Lock &amp; Approve Payroll
          </button>
        </div>
      ) : (
        <div className="rounded-xl p-4 bg-emerald-500/10 border border-emerald-500/30 text-center">
          <p className="text-sm text-emerald-300 mb-3">
            This locks the batch and commits withheld balances. Numbers cannot be changed after this point. Continue?
          </p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => { setShowConfirm(false); setLockError(null); }}
              className="px-4 py-2 rounded-lg text-sm text-white/60 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleLockAndApprove}
              disabled={locking}
              className="px-6 py-2 rounded-lg text-sm font-medium bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-50 inline-flex items-center gap-2"
            >
              {locking ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Locking...
                </>
              ) : (
                "Confirm & Lock"
              )}
            </button>
          </div>
        </div>
      )}

      {/* Admin controls — go back to Rates step */}
      {isAdmin && onGoBack && (
        <div className="mt-6 text-center">
          <button
            onClick={onGoBack}
            className="text-xs text-white/30 hover:text-white/60 transition-colors inline-flex items-center gap-1"
          >
            <RotateCcw className="w-3 h-3" />
            Go back to Rates step
          </button>
        </div>
      )}
    </div>
  );
}

// ── Step 3: Excel Export ────────────────────────────────────────────────────

function ExportStep({
  batchId,
  status,
  onAdvance,
  advancing,
  isAdmin,
  onReopen,
}: {
  batchId: number;
  status: BatchStatus;
  onAdvance: (force?: boolean) => void;
  advancing: boolean;
  isAdmin: boolean;
  onReopen: () => Promise<void>;
}) {
  const isEverDriven = status.source === "maz";
  const exported = !!status.paychex_exported_at;

  async function downloadExcel() {
    try {
      const res = await fetch(`/api/data/workflow/${batchId}/export-excel`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error("Download failed");

      // Extract filename from Content-Disposition; fall back to generic name
      let filename = `payroll_batch_${batchId}.xlsx`;
      const disposition = res.headers.get("Content-Disposition");
      if (disposition) {
        const match = disposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
        if (match) filename = decodeURIComponent(match[1].trim());
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 5000);

      if (isEverDriven) {
        toast.success("EverDriven Excel downloaded", {
          description: `Saved as ${filename}. Continue to paystubs when ready.`,
        });
        // ED batches don't stamp paychex_exported_at — no reload needed
      } else {
        toast.success("Paychex Excel downloaded", {
          description: `Saved as ${filename}. Enter the totals into Paychex Flex, then continue.`,
        });
        // Backend stamped paychex_exported_at — reload to pick it up
        window.location.reload();
      }
    } catch (e) {
      toast.error("Download failed — try again", {
        description: e instanceof Error ? e.message : "Check your connection or reload the page.",
      });
    }
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-white mb-4">Export to Excel</h2>

      {isEverDriven ? (
        <div className="text-center py-8">
          <FileSpreadsheet className="w-12 h-12 text-[#667eea] mx-auto mb-3" />
          <p className="text-white/70 mb-1">
            EverDriven batches don&apos;t use Paychex.
          </p>
          <p className="text-sm text-white/40 mb-4">
            Download the payroll Excel for your records, then continue to paystubs.
          </p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={downloadExcel}
              className="px-4 py-2 rounded-lg text-sm text-white/80 hover:text-white border border-white/20 hover:border-white/40 transition-colors inline-flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Download Excel
            </button>
            <button
              onClick={() => onAdvance()}
              disabled={advancing}
              className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
            >
              {advancing ? "Advancing..." : "Continue to Paystubs"}
            </button>
          </div>
        </div>
      ) : exported ? (
        <div className="text-center py-8">
          <Check className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
          <p className="text-white/70 mb-4">Excel has been downloaded.</p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={downloadExcel}
              className="px-4 py-2 rounded-lg text-sm text-white/60 hover:text-white border border-white/20 hover:border-white/40 transition-colors inline-flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Download Again
            </button>
            <button
              onClick={() => onAdvance()}
              disabled={advancing}
              className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
            >
              {advancing ? "Advancing..." : "Continue to Paystubs"}
            </button>
          </div>
        </div>
      ) : (
        <div className="text-center py-8">
          <FileSpreadsheet className="w-12 h-12 text-[#667eea] mx-auto mb-3" />
          <p className="text-white/70 mb-4">
            Download the payroll Excel. Enter the totals into Paychex Flex, then continue to paystubs.
          </p>
          <button
            onClick={downloadExcel}
            className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors inline-flex items-center gap-2"
          >
            <Download className="w-4 h-4" />
            Download Excel
          </button>
        </div>
      )}

      {/* Admin: Reset Batch to Review */}
      {isAdmin && <AdminResetButton onReopen={onReopen} />}
    </div>
  );
}

// ── Step 4: Paystub Sending ─────────────────────────────────────────────────

interface EmailPreview {
  subject: string;
  body_html: string;
  driver_name: string;
  email: string;
}

function EmailPreviewModal({
  preview,
  onClose,
}: {
  preview: EmailPreview;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl bg-[#1a1a2e] border border-white/10 shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
          <div>
            <p className="text-xs text-white/40 mb-0.5">To: {preview.email}</p>
            <p className="text-sm font-semibold text-white">
              {preview.subject}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 text-white/50 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto bg-white">
          <iframe
            srcDoc={preview.body_html}
            title="Email Preview"
            className="w-full min-h-[500px] border-0"
            sandbox="allow-same-origin"
          />
        </div>
      </div>
    </div>
  );
}

interface EmailTemplate {
  subject: string;
  body: string;
}

function EmailTemplateModal({
  batchId,
  onClose,
}: {
  batchId: number;
  onClose: () => void;
}) {
  const [tmpl, setTmpl] = useState<EmailTemplate | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .get<EmailTemplate>(`/api/data/workflow/${batchId}/email-template`)
      .then(setTmpl)
      .catch((e) => { console.error(e); toast.error('Failed to load email template') });
  }, [batchId]);

  async function save() {
    if (!tmpl) return;
    setSaving(true);
    try {
      await api.post(`/api/data/workflow/${batchId}/email-template`, tmpl);
      setSaved(true);
      setTimeout(() => {
        setSaved(false);
        onClose();
      }, 1000);
    } catch (e) {
      console.error(e);
      toast.error('Failed to save email template');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl flex flex-col rounded-2xl bg-[#1a1a2e] border border-white/10 shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
          <div>
            <p className="text-sm font-semibold text-white">
              Edit Paystub Email
            </p>
            <p className="text-xs text-white/40 mt-0.5">
              This sets the email body for all drivers in this batch. Use{" "}
              <span className="font-mono bg-white/10 px-1 rounded">
                [First Name]
              </span>
              ,{" "}
              <span className="font-mono bg-white/10 px-1 rounded">
                [Total Pay]
              </span>
              ,{" "}
              <span className="font-mono bg-white/10 px-1 rounded">
                [Ride Count]
              </span>
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 text-white/50 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        {!tmpl ? (
          <div className="p-8 text-center text-white/40 text-sm">
            Loading...
          </div>
        ) : (
          <div className="p-5 space-y-4">
            <div>
              <label className="text-xs text-white/40 uppercase tracking-wide mb-1.5 block">
                Subject
              </label>
              <input
                type="text"
                value={tmpl.subject}
                onChange={(e) => setTmpl({ ...tmpl, subject: e.target.value })}
                className="w-full px-3 py-2 rounded-lg text-sm border border-white/20 bg-white/5 text-white focus:outline-none focus:border-[#667eea]"
              />
            </div>
            <div>
              <label className="text-xs text-white/40 uppercase tracking-wide mb-1.5 block">
                Email Body
              </label>
              <textarea
                value={tmpl.body}
                onChange={(e) => setTmpl({ ...tmpl, body: e.target.value })}
                rows={10}
                className="w-full px-3 py-2 rounded-lg text-sm border border-white/20 bg-white/5 text-white focus:outline-none focus:border-[#667eea] font-mono resize-y"
              />
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="px-4 py-2 rounded-lg text-sm text-white/50 hover:text-white border border-white/20 hover:border-white/40 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-[#667eea] text-white hover:bg-[#5a6fd6] transition-colors disabled:opacity-50"
              >
                {saved ? "✓ Saved" : saving ? "Saving..." : "Save Template"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function InlineStubEmailEditor({
  batchId,
  driver,
  onSaved,
}: {
  batchId: number;
  driver: StubDriver;
  onSaved: (personId: number, newEmail: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(driver.email || "");
  const [saving, setSaving] = useState(false);

  async function save() {
    const trimmed = val.trim();
    if (!trimmed) return;
    setSaving(true);
    try {
      await api.patch(
        `/api/data/workflow/${batchId}/update-person/${driver.person_id}`,
        { email: trimmed },
      );
      onSaved(driver.person_id, trimmed);
      setEditing(false);
    } catch (e) {
      console.error(e);
      toast.error('Failed to update email address');
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <button
        onClick={() => {
          setEditing(true);
          setVal(driver.email || "");
        }}
        className="flex items-center gap-1 text-xs text-white/50 hover:text-white/80 transition-colors group"
        title="Click to edit email"
      >
        <span>{driver.email || "—"}</span>
        <Pencil className="w-2.5 h-2.5 opacity-0 group-hover:opacity-60 transition-opacity" />
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <input
        type="email"
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") setEditing(false);
        }}
        autoFocus
        className="w-44 px-1.5 py-0.5 rounded text-xs border border-white/20 bg-white/5 text-white focus:outline-none focus:border-[#667eea]"
      />
      <button
        onClick={save}
        disabled={saving}
        className="text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
      >
        {saving ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : (
          <Check className="w-3 h-3" />
        )}
      </button>
      <button
        onClick={() => setEditing(false)}
        className="text-white/30 hover:text-white/60"
      >
        <X className="w-3 h-3" />
      </button>
    </div>
  );
}

interface SendProgress {
  current: number;
  total: number;
  currentDriver: string;
  sent: number;
  failed: number;
  noEmail: number;
}

function StubsStep({
  batchId,
  status,
  onAdvance,
  advancing,
  onRefresh,
  isAdmin,
  onReopen,
}: {
  batchId: number;
  status: BatchStatus;
  onAdvance: (force?: boolean) => void;
  advancing: boolean;
  onRefresh: () => Promise<void>;
  isAdmin: boolean;
  onReopen: () => Promise<void>;
}) {
  const [data, setData] = useState<StubsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendProgress, setSendProgress] = useState<SendProgress | null>(null);
  const [sendResult, setSendResult] = useState<{
    sent: number;
    failed: number;
  } | null>(null);
  const [retrying, setRetrying] = useState<number | null>(null);
  const [preview, setPreview] = useState<EmailPreview | null>(null);
  const [loadingPreview, setLoadingPreview] = useState<number | null>(null);
  const [showTemplateEditor, setShowTemplateEditor] = useState(false);
  const [generatingPaychex, setGeneratingPaychex] = useState(false);
  const [paychexError, setPaychexError] = useState<string | null>(null);

  // Admin-only state
  const [showTestSendDialog, setShowTestSendDialog] = useState(false);
  const [testSending, setTestSending] = useState(false);
  const [testSendResult, setTestSendResult] = useState<{ sent: number; failed: number } | null>(null);

  // Gmail pre-flight state
  interface GmailAccountStatus {
    account: string;
    ok: boolean;
    error: string | null;
    scopes: string[];
    from_email: string;
    reauth_url?: string;
  }
  const [gmailStatus, setGmailStatus] = useState<GmailAccountStatus[] | null>(null);
  const [gmailStatusLoading, setGmailStatusLoading] = useState(true);

  const isFA = status.source !== "maz";
  const paychexConfirmed = !isFA || !!status.paychex_exported_at;

  // The account this batch needs: maz batches use maz, everything else uses acumen
  const neededAccount = status.source === "maz" ? "maz" : "acumen";
  const gmailAccountStatus = gmailStatus?.find((a) => a.account === neededAccount) ?? null;
  const gmailOk = gmailStatusLoading || gmailAccountStatus?.ok !== false;

  async function generatePaychex() {
    setGeneratingPaychex(true);
    setPaychexError(null);
    try {
      const res = await api.post<{ ok: boolean; error?: string }>(
        `/api/data/workflow/${batchId}/generate-paychex`,
      );
      if (!res.ok) {
        setPaychexError(res.error ?? "Generation failed — check backend logs.");
      } else {
        await onRefresh();
      }
    } catch (e: unknown) {
      setPaychexError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setGeneratingPaychex(false);
    }
  }

  async function handleTestSend() {
    if (!data) return;
    // Count all drivers with email (not just pending) — test send targets all
    const allWithEmail = data.drivers.filter(
      (d) => d.status !== "withheld" && d.status !== "settled_externally" && d.email
    );
    const count = allWithEmail.length;
    setTestSending(true);
    setTestSendResult(null);
    setShowTestSendDialog(false);
    try {
      const res = await api.post<{ ok: boolean; sent: number; failed: number; error?: string }>(
        `/api/data/workflow/${batchId}/send-stubs?confirmed_recipient_count=${count}&test_recipient_override=milionmalik.co%40gmail.com`,
        {},
      );
      if (res.ok) {
        setTestSendResult({ sent: res.sent, failed: res.failed });
        toast.success(`Test send complete — ${res.sent} stubs sent to your inbox`, {
          description: "No drivers received anything.",
        });
      } else {
        toast.error("Test send failed", { description: res.error ?? "Unknown error" });
      }
    } catch (e: unknown) {
      toast.error("Test send failed", {
        description: e instanceof Error ? e.message : "Unknown error",
      });
    } finally {
      setTestSending(false);
    }
  }

  const fetchStatus = useCallback(() => {
    setFetchError(null);
    return api
      .get<StubsStatus>(`/api/data/workflow/${batchId}/stubs-status`)
      .then(setData)
      .catch((e: unknown) => {
        console.error("stubs-status fetch failed", e);
        toast.error("Stubs status check failed");
        setFetchError(
          e instanceof Error ? e.message : "Failed to load paystub status",
        );
      });
  }, [batchId]);

  useEffect(() => {
    fetchStatus().finally(() => setLoading(false));
  }, [fetchStatus]);

  // Gmail pre-flight: fetch on mount to surface broken tokens before mom clicks Send
  useEffect(() => {
    setGmailStatusLoading(true);
    api
      .get<{ accounts: GmailAccountStatus[] }>("/admin/gmail-reauth/status")
      .then((res) => setGmailStatus(res.accounts))
      .catch(() => {
        // Non-fatal: if the check itself fails (network, auth) don't block sending
        setGmailStatus(null);
      })
      .finally(() => setGmailStatusLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function sendAll() {
    if (!data) return;
    setSending(true);
    setSendResult(null);

    const pendingDrivers = data.drivers.filter(
      (d) => d.status === "pending" || d.status === "failed",
    );
    const total = pendingDrivers.length;
    const prog: SendProgress = {
      current: 0,
      total,
      currentDriver: "",
      sent: 0,
      failed: 0,
      noEmail: 0,
    };
    setSendProgress({ ...prog });

    for (let i = 0; i < pendingDrivers.length; i++) {
      const driver = pendingDrivers[i];
      prog.current = i + 1;
      prog.currentDriver = driver.name;
      setSendProgress({ ...prog });

      try {
        const res = await api.post<{
          ok: boolean;
          status: string;
          name: string;
          error?: string;
        }>(`/api/data/workflow/${batchId}/send-stub/${driver.person_id}`);
        const st =
          res.status === "sent" || res.status === "already_sent"
            ? "sent"
            : res.status === "no_email"
              ? "no_email"
              : "failed";
        if (st === "sent") prog.sent++;
        else if (st === "no_email") prog.noEmail++;
        else prog.failed++;

        setData((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            drivers: prev.drivers.map((d) =>
              d.person_id === driver.person_id
                ? { ...d, status: st as any }
                : d,
            ),
            counts: {
              sent: prev.counts.sent + (st === "sent" ? 1 : 0),
              failed:
                prev.counts.failed +
                (st === "failed" ? 1 : 0) -
                (driver.status === "failed" && st !== "failed" ? 1 : 0),
              no_email: prev.counts.no_email + (st === "no_email" ? 1 : 0),
              withheld: prev.counts.withheld,
              settled_externally: prev.counts.settled_externally ?? 0,
              pending:
                prev.counts.pending - (driver.status === "pending" ? 1 : 0),
            },
          };
        });
      } catch {
        prog.failed++;
        setData((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            drivers: prev.drivers.map((d) =>
              d.person_id === driver.person_id ? { ...d, status: "failed" } : d,
            ),
            counts: {
              ...prev.counts,
              failed: prev.counts.failed + 1,
              pending:
                prev.counts.pending - (driver.status === "pending" ? 1 : 0),
            },
          };
        });
      }
      setSendProgress({ ...prog });
    }

    setSendResult({ sent: prog.sent, failed: prog.failed });
    setTimeout(() => setSendProgress(null), 2000);
    await fetchStatus();
    await onRefresh();
    setSending(false);

    if (prog.failed > 0 && prog.sent === 0) {
      toast.error("Send Stubs failed — no stubs delivered", {
        description: `${prog.failed} driver${prog.failed !== 1 ? "s" : ""} failed. Check email addresses or backend connection.`,
      });
    } else if (prog.failed > 0) {
      toast.error(`${prog.failed} stub${prog.failed !== 1 ? "s" : ""} failed to send`, {
        description: `${prog.sent} sent successfully. Check email addresses for the failed drivers.`,
      });
    } else {
      toast.success(`Stubs sent to ${prog.sent} driver${prog.sent !== 1 ? "s" : ""}`, {
        description: "All paystubs delivered. Drivers will receive their email shortly.",
      });
    }
  }

  async function retryOne(personId: number) {
    setRetrying(personId);
    try {
      await api.post(`/api/data/workflow/${batchId}/retry-stub/${personId}`);
      await fetchStatus();
    } catch (e) {
      console.error(e);
      toast.error('Failed to retry stub send');
    } finally {
      setRetrying(null);
    }
  }

  async function showPreview(personId: number) {
    setLoadingPreview(personId);
    try {
      const p = await api.get<EmailPreview>(
        `/api/data/workflow/${batchId}/preview-stub/${personId}`,
      );
      setPreview(p);
    } catch (e) {
      console.error(e);
      toast.error('Failed to load email preview');
    } finally {
      setLoadingPreview(null);
    }
  }

  function handleEmailSaved(personId: number, newEmail: string) {
    if (!data) return;
    setData({
      ...data,
      drivers: data.drivers.map((d) =>
        d.person_id === personId
          ? {
              ...d,
              email: newEmail,
              status: d.status === "no_email" ? "pending" : d.status,
            }
          : d,
      ),
      counts: {
        ...data.counts,
        no_email: data.drivers.filter(
          (d) => d.person_id !== personId && d.status === "no_email",
        ).length,
        pending: data.drivers.filter((d) =>
          d.person_id === personId ? true : d.status === "pending",
        ).length,
      },
    });
  }

  if (loading) return <LoadingSpinner />;
  if (fetchError || !data) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/8 px-5 py-6 text-center space-y-3">
        <AlertTriangle className="w-8 h-8 text-red-400 mx-auto" />
        <p className="text-sm font-medium text-red-300">
          {fetchError ?? "Could not load paystub list"}
        </p>
        <button
          onClick={() => {
            setLoading(true);
            fetchStatus().finally(() => setLoading(false));
          }}
          className="px-4 py-1.5 rounded-lg text-xs font-medium bg-red-500/20 text-red-300 hover:bg-red-500/30 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  const { drivers, counts } = data;
  const allDone = counts.pending === 0 && counts.failed === 0;
  const progress =
    data.total > 0
      ? Math.round(
          ((counts.sent + counts.no_email + counts.withheld + (counts.settled_externally ?? 0)) / data.total) *
            100,
        )
      : 0;
  const sendPct = sendProgress
    ? Math.round((sendProgress.current / sendProgress.total) * 100)
    : 0;

  return (
    <div>
      {preview && (
        <EmailPreviewModal preview={preview} onClose={() => setPreview(null)} />
      )}
      {showTemplateEditor && (
        <EmailTemplateModal
          batchId={batchId}
          onClose={() => setShowTemplateEditor(false)}
        />
      )}

      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Send Paystubs</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowTemplateEditor(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-white/50 hover:text-white border border-white/20 hover:border-white/40 transition-colors"
          >
            <Pencil className="w-3 h-3" /> Edit Email
          </button>
          <Badge variant="success">{counts.sent} sent</Badge>
          {counts.failed > 0 && (
            <Badge variant="danger">{counts.failed} failed</Badge>
          )}
          {counts.no_email > 0 && (
            <Badge variant="default">{counts.no_email} no email</Badge>
          )}
          {counts.withheld > 0 && (
            <Badge variant="default">{counts.withheld} withheld</Badge>
          )}
          {(counts.settled_externally ?? 0) > 0 && (
            <Badge variant="default">
              <span className="text-violet-400">{counts.settled_externally} paid externally</span>
            </Badge>
          )}
          {counts.pending > 0 && (
            <Badge variant="warning">{counts.pending} pending</Badge>
          )}
        </div>
      </div>

      {/* Gmail pre-flight banner */}
      {!gmailStatusLoading && gmailStatus !== null && (
        <AnimatePresence mode="wait">
          {!gmailOk && gmailAccountStatus ? (
            <motion.div
              key="gmail-broken"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="mb-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                  <p className="text-sm text-red-300 font-medium">
                    Gmail auth broken for <span className="font-bold">{gmailAccountStatus.account}</span> — emails will fail
                  </p>
                </div>
                {gmailAccountStatus.reauth_url && (
                  <a
                    href={gmailAccountStatus.reauth_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/20 text-red-300 hover:bg-red-500/30 border border-red-500/30 transition-colors"
                  >
                    Click to reauth
                  </a>
                )}
              </div>
              {gmailAccountStatus.error && (
                <p className="mt-1.5 text-xs text-red-400/70 font-mono">{gmailAccountStatus.error}</p>
              )}
            </motion.div>
          ) : (
            <motion.div
              key="gmail-ok"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="mb-4 flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-emerald-500/8 border border-emerald-500/20"
            >
              <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <p className="text-sm text-emerald-300">Gmail auth OK — ready to send</p>
            </motion.div>
          )}
        </AnimatePresence>
      )}

      {/* Paychex confirmation banner — FA batches only */}
      {isFA && (
        <AnimatePresence mode="wait">
          {paychexConfirmed ? (
            <motion.div
              key="paychex-ok"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="mb-4 flex items-center gap-3 px-4 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/25"
            >
              <Check className="w-4 h-4 text-emerald-400 shrink-0" />
              <p className="text-sm text-emerald-300 font-medium">
                Paychex generated — safe to send paystubs
              </p>
            </motion.div>
          ) : (
            <motion.div
              key="paychex-pending"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="mb-4 px-4 py-3 rounded-xl bg-amber-500/10 border border-amber-500/25"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                  <p className="text-sm text-amber-300 font-medium">
                    Paychex not generated yet — do this before sending emails
                  </p>
                </div>
                <button
                  onClick={generatePaychex}
                  disabled={generatingPaychex}
                  className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 border border-amber-500/30 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
                >
                  {generatingPaychex ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <FileSpreadsheet className="w-3 h-3" />
                  )}
                  {generatingPaychex ? "Generating..." : "Generate Now"}
                </button>
              </div>
              {paychexError && (
                <p className="mt-2 text-xs text-red-400">{paychexError}</p>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      )}

      {/* Sending progress card */}
      <AnimatePresence>
        {sendProgress && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="mb-5 rounded-xl border dark:border-white/10 border-gray-200 dark:bg-white/[0.03] bg-white p-4"
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 text-[#667eea] animate-spin" />
                <span className="text-sm font-medium dark:text-white text-gray-900">
                  Sending emails...
                </span>
              </div>
              <span className="text-sm dark:text-white/60 text-gray-500">
                {sendProgress.current} / {sendProgress.total}
              </span>
            </div>
            <div className="w-full h-2.5 dark:bg-white/10 bg-gray-200 rounded-full overflow-hidden mb-3">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${sendPct}%` }}
                transition={{ duration: 0.3 }}
                className="h-full rounded-full bg-gradient-to-r from-[#667eea] to-[#06b6d4] transition-all duration-300"
              />
            </div>
            {sendProgress.currentDriver && (
              <p className="text-sm dark:text-white/60 text-gray-500 mb-2 truncate">
                <Mail className="w-3.5 h-3.5 inline mr-1.5 -mt-0.5" />
                {sendProgress.current <= sendProgress.total
                  ? "Sending to"
                  : "Finished with"}{" "}
                <span className="dark:text-white/80 text-gray-700 font-medium">
                  {sendProgress.currentDriver}
                </span>
              </p>
            )}
            <div className="flex items-center gap-4 text-xs">
              {sendProgress.sent > 0 && (
                <span className="flex items-center gap-1 text-emerald-400">
                  <Check className="w-3 h-3" /> {sendProgress.sent} sent
                </span>
              )}
              {sendProgress.failed > 0 && (
                <span className="flex items-center gap-1 text-red-400">
                  <AlertTriangle className="w-3 h-3" /> {sendProgress.failed}{" "}
                  failed
                </span>
              )}
              {sendProgress.noEmail > 0 && (
                <span className="flex items-center gap-1 dark:text-white/40 text-gray-400">
                  <X className="w-3 h-3" /> {sendProgress.noEmail} no email
                </span>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Overall progress bar (when not actively sending) */}
      {!sendProgress && (
        <div className="w-full h-2 rounded-full dark:bg-white/10 bg-gray-200 mb-4 overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.5 }}
            className="h-full rounded-full bg-gradient-to-r from-[#667eea] to-[#06b6d4]"
          />
        </div>
      )}

      {/* Send result feedback */}
      {sendResult && !sendProgress && (
        <div
          className={`mb-4 px-4 py-2.5 rounded-xl text-sm font-medium ${
            sendResult.failed === -1
              ? "bg-red-500/15 text-red-400"
              : sendResult.failed > 0
                ? "bg-amber-500/15 text-amber-400"
                : "bg-emerald-500/15 text-emerald-400"
          }`}
        >
          {sendResult.failed === -1
            ? "Send failed — check backend connection"
            : `Sent ${sendResult.sent}${sendResult.failed > 0 ? ` · ${sendResult.failed} failed (check email addresses)` : ""}`}
        </div>
      )}

      {/* Send All / Retry All buttons */}
      {(counts.pending > 0 || counts.failed > 0) && !sending && (
        <div className="text-center mb-4 flex items-center justify-center gap-3">
          {counts.pending > 0 && (
            <button
              onClick={sendAll}
              disabled={sending || !paychexConfirmed || !gmailOk}
              title={
                !paychexConfirmed
                  ? "Generate Paychex first"
                  : !gmailOk
                    ? "Gmail auth broken — reauth before sending"
                    : undefined
              }
              className="px-6 py-2.5 rounded-xl bg-[#667eea] text-white font-medium hover:bg-[#5a6fd6] transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
            >
              <Send className="w-4 h-4" />
              {`Send All Paystubs (${counts.pending})`}
            </button>
          )}
          {counts.failed > 0 && (
            <button
              onClick={sendAll}
              disabled={sending || !paychexConfirmed || !gmailOk}
              title={
                !paychexConfirmed
                  ? "Generate Paychex first"
                  : !gmailOk
                    ? "Gmail auth broken — reauth before sending"
                    : undefined
              }
              className="px-6 py-2.5 rounded-xl bg-red-500/20 text-red-300 font-medium hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2 border border-red-500/30"
            >
              <RotateCcw className="w-4 h-4" />
              {`Retry All Failed (${counts.failed})`}
            </button>
          )}
        </div>
      )}

      {/* Admin: Test send dialog */}
      {isAdmin && showTestSendDialog && data && (
        <div className="mb-4 rounded-xl border border-[#667eea]/40 bg-[#667eea]/8 p-4">
          <p className="text-sm font-medium text-white mb-1">
            Send all {data.drivers.filter((d) => d.status !== "withheld" && d.status !== "settled_externally" && d.email).length} paystubs to your inbox
          </p>
          <p className="text-xs text-white/50 mb-3">
            Every stub goes to milionmalik.co@gmail.com. No drivers receive anything. Logged as test.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowTestSendDialog(false)}
              className="px-3 py-1.5 rounded-lg text-xs text-white/50 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleTestSend}
              disabled={testSending}
              className="px-4 py-1.5 rounded-lg text-xs font-medium bg-[#667eea] text-white hover:bg-[#5a6fd6] transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
            >
              {testSending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
              {testSending ? "Sending..." : "Yes, send to me"}
            </button>
          </div>
        </div>
      )}

      {/* Admin: "Send all stubs to me" button */}
      {isAdmin && !showTestSendDialog && (
        <div className="text-center mb-3">
          <button
            onClick={() => setShowTestSendDialog(true)}
            disabled={testSending}
            className="px-4 py-1.5 rounded-lg text-xs font-medium border border-[#667eea]/40 text-[#667eea] hover:bg-[#667eea]/10 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
          >
            {testSending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
            {testSending ? "Sending test..." : "Send all stubs to me (test)"}
          </button>
          {testSendResult && (
            <p className="text-xs text-white/40 mt-1">
              Test sent: {testSendResult.sent} delivered{testSendResult.failed > 0 ? `, ${testSendResult.failed} failed` : ""}
            </p>
          )}
        </div>
      )}

      {/* Admin: Reset Batch to Review */}
      {isAdmin && <AdminResetButton onReopen={onReopen} />}

      {/* Driver list */}
      <div className="rounded-xl overflow-hidden dark:bg-white/5 dark:border dark:border-white/10 mb-6">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-white/40 text-xs uppercase">
                <th className="px-4 py-2.5">Driver</th>
                <th className="px-4 py-2.5">Email</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {drivers.map((d) => {
                const isCurrentlySending =
                  sending &&
                  sendProgress?.currentDriver === d.name &&
                  sendProgress.current <= sendProgress.total;
                return (
                  <tr
                    key={d.person_id}
                    className={`border-t border-white/5 transition-colors duration-300 ${isCurrentlySending ? "dark:bg-[#667eea]/10 bg-blue-50" : ""}`}
                  >
                    <td className="px-4 py-2 text-white text-sm">
                      <span className="flex items-center gap-2">
                        {isCurrentlySending && (
                          <Loader2 className="w-3 h-3 text-[#667eea] animate-spin flex-shrink-0" />
                        )}
                        {d.name}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      {d.status === "sent" ? (
                        <span className="text-xs text-white/40">
                          {d.email || "—"}
                        </span>
                      ) : (
                        <InlineStubEmailEditor
                          batchId={batchId}
                          driver={d}
                          onSaved={handleEmailSaved}
                        />
                      )}
                    </td>
                    <td className="px-4 py-2">
                      {d.status === "sent" && (
                        <Badge variant="success">Sent</Badge>
                      )}
                      {d.status === "failed" && (
                        <span title={d.error ?? undefined} className="inline-flex flex-col items-start gap-0.5">
                          <Badge variant="danger">Failed</Badge>
                          {d.error && (
                            <span className="text-[10px] text-red-300/80 max-w-[260px] truncate" title={d.error}>
                              {d.error}
                            </span>
                          )}
                        </span>
                      )}
                      {d.status === "no_email" && (
                        <Badge variant="default">No Email</Badge>
                      )}
                      {d.status === "withheld" && (
                        <Badge variant="default">Withheld</Badge>
                      )}
                      {d.status === "settled_externally" && (
                        <Badge variant="default">
                          <span className="text-violet-400">Paid Externally</span>
                        </Badge>
                      )}
                      {d.status === "pending" && !isCurrentlySending && (
                        <Badge variant="warning">Pending</Badge>
                      )}
                      {isCurrentlySending && (
                        <span className="text-xs text-[#667eea] font-medium">
                          Sending...
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex items-center gap-2 justify-end">
                        {d.status !== "sent" && !sending && (
                          <button
                            onClick={() => showPreview(d.person_id)}
                            disabled={loadingPreview === d.person_id}
                            className="text-xs text-white/40 hover:text-white/70 transition-colors inline-flex items-center gap-1"
                            title="Preview email"
                          >
                            {loadingPreview === d.person_id ? (
                              <Loader2 className="w-3 h-3 animate-spin" />
                            ) : (
                              <Eye className="w-3 h-3" />
                            )}
                          </button>
                        )}
                        {d.status === "failed" && !sending && (
                          <button
                            onClick={() => retryOne(d.person_id)}
                            disabled={retrying === d.person_id}
                            className="text-xs text-[#667eea] hover:underline inline-flex items-center gap-1"
                          >
                            <RefreshCw
                              className={`w-3 h-3 ${retrying === d.person_id ? "animate-spin" : ""}`}
                            />
                            Retry
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Complete button */}
      {allDone && !sending && (
        <div className="text-center">
          <button
            onClick={() => onAdvance()}
            disabled={advancing}
            className="px-6 py-2.5 rounded-xl bg-emerald-600 text-white font-medium hover:bg-emerald-500 transition-colors disabled:opacity-50"
          >
            {advancing ? "Completing..." : "Complete Batch"}
          </button>
        </div>
      )}
      {!allDone && counts.pending === 0 && counts.failed > 0 && !sending && (
        <div className="text-center">
          <button
            onClick={() => onAdvance(true)}
            disabled={advancing}
            className="text-sm text-white/40 hover:text-white/60 transition-colors inline-flex items-center gap-1"
          >
            <SkipForward className="w-3.5 h-3.5" />
            {advancing ? "Completing..." : "Complete anyway (skip failures)"}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Step 5: Complete ────────────────────────────────────────────────────────

function CompleteStep({
  status,
  isAdmin,
  onReopen,
}: {
  status: BatchStatus;
  isAdmin: boolean;
  onReopen: () => Promise<void>;
}) {
  const router = useRouter();
  const batchId = status.batch_id;
  const [showResendDialog, setShowResendDialog] = useState(false);
  const [resending, setResending] = useState(false);
  const [resendResult, setResendResult] = useState<{ sent: number; failed: number } | null>(null);

  async function handleResendStubs(driverCount: number) {
    setResending(true);
    setShowResendDialog(false);
    try {
      const res = await api.post<{ ok: boolean; sent: number; failed: number; error?: string }>(
        `/api/data/workflow/${batchId}/resend-stubs?confirmed_recipient_count=${driverCount}`,
        {},
      );
      if (res.ok) {
        setResendResult({ sent: res.sent, failed: res.failed });
        toast.success(`Resent ${res.sent} stubs`, {
          description: res.failed > 0 ? `${res.failed} failed — check driver email addresses.` : "All delivered.",
        });
      } else {
        toast.error("Resend failed", { description: res.error ?? "Unknown error" });
      }
    } catch (e: unknown) {
      toast.error("Resend failed", { description: e instanceof Error ? e.message : "Unknown error" });
    } finally {
      setResending(false);
    }
  }

  return (
    <div className="text-center py-12">
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: "spring", stiffness: 300, damping: 20 }}
      >
        <Check className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
      </motion.div>
      <h2 className="text-xl font-bold text-white mb-2">Batch Complete!</h2>
      <p className="text-white/50 mb-1">
        {status.company} · {status.rides} rides · {status.driver_count} drivers
      </p>
      <p className="text-emerald-400 font-medium mb-6">
        {formatCurrency(status.margin)} margin
      </p>

      {/* Send to Paychex — FA batches only. Shown here so mom doesn't have to
          navigate to history to trigger the bot after completing the workflow. */}
      {status.source !== "maz" && (
        <div className="flex justify-center mb-6">
          <PaychexBotPanel batchId={batchId} />
        </div>
      )}

      <div className="flex items-center justify-center gap-3">
        <button
          onClick={() => router.push("/payroll/workflow")}
          className="px-4 py-2 rounded-lg text-sm text-white/60 hover:text-white border border-white/20 hover:border-white/40 transition-colors"
        >
          Back to Workflow
        </button>
        <button
          onClick={() =>
            router.push(`/payroll/workflow/${status.batch_id}/summary`)
          }
          className="px-4 py-2 rounded-lg text-sm font-medium bg-[#667eea] text-white hover:bg-[#5a6fd6] transition-colors"
        >
          View Summary & Download
        </button>
      </div>

      {/* Admin: Resend Stubs + Reset Batch */}
      {isAdmin && (
        <div className="mt-8 flex flex-col items-center gap-3">
          {/* Resend stubs */}
          {!showResendDialog ? (
            <button
              onClick={() => setShowResendDialog(true)}
              disabled={resending}
              className="px-4 py-2 rounded-lg text-sm border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 transition-colors inline-flex items-center gap-1.5 disabled:opacity-50"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              {resending ? "Resending..." : "Resend Stubs to All Drivers"}
            </button>
          ) : (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/8 p-4 max-w-sm text-left">
              <p className="text-sm font-medium text-amber-300 mb-1">
                Resend to all {status.driver_count} drivers?
              </p>
              <p className="text-xs text-white/50 mb-3">
                Real emails go out to every driver's inbox. Use this if the original send failed for some drivers.
              </p>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setShowResendDialog(false)}
                  className="px-3 py-1.5 rounded-lg text-xs text-white/50 hover:text-white transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleResendStubs(status.driver_count)}
                  disabled={resending}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 border border-amber-500/30 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
                >
                  {resending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
                  Yes, resend to {status.driver_count} drivers
                </button>
              </div>
            </div>
          )}
          {resendResult && (
            <p className="text-xs text-white/40">
              Resent: {resendResult.sent} delivered{resendResult.failed > 0 ? `, ${resendResult.failed} failed` : ""}
            </p>
          )}

          <AdminResetButton onReopen={onReopen} />
        </div>
      )}
    </div>
  );
}
