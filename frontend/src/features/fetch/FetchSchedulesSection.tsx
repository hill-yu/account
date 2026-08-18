import { useEffect, useMemo, useState } from "react";

import { api, type ApiError } from "../../lib/api";
import { getErrorMessage } from "../../lib/errorMessages";
import { formatDateTime, formatNullable } from "../../lib/format";
import { SectionCard } from "../../components/ui/SectionCard";
import { Field } from "../../components/ui/Field";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { useToast } from "../../components/ui/useToast";
import type {
  AccountRead,
  FetchScheduleCreate,
  FetchScheduleMode,
  FetchScheduleRead,
  FetchScheduleUpdate,
  InstanceRead,
} from "../../types/api";

type ScheduleFormState = {
  account_id: string;
  collector_instance_id: string;
  enabled: boolean;
  mode: FetchScheduleMode;
  daily_times_text: string;
  interval_hours: string;
  timezone: string;
};

type ManualFetchFormState = {
  account_id: string;
  collector_instance_id: string;
  report_date: string;
};

const DEFAULT_DAILY_TIMES = "08:00,20:00";
const DEFAULT_INTERVAL_HOURS = "4";

function buildInitialScheduleForm(accounts: AccountRead[]): ScheduleFormState {
  return {
    account_id: "",
    collector_instance_id: "",
    enabled: true,
    mode: "daily_times",
    daily_times_text: DEFAULT_DAILY_TIMES,
    interval_hours: DEFAULT_INTERVAL_HOURS,
    timezone: accounts[0]?.timezone ?? "Asia/Shanghai",
  };
}

function parseDailyTimes(raw: string): string[] {
  const items = raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  if (items.length === 0) {
    throw new Error("Please enter at least one HH:MM time.");
  }

  for (const item of items) {
    if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(item)) {
      throw new Error(`Invalid time: ${item}. Use HH:MM, for example 08:00.`);
    }
  }

  return Array.from(new Set(items)).sort();
}

function buildSchedulePayload(form: ScheduleFormState): FetchScheduleCreate {
  const payload: FetchScheduleCreate = {
    account_id: Number(form.account_id),
    collector_instance_id: Number(form.collector_instance_id),
    enabled: form.enabled,
    mode: form.mode,
    daily_times: null,
    interval_hours: null,
    timezone: form.timezone.trim(),
  };

  if (!payload.timezone) {
    throw new Error("Timezone is required.");
  }

  if (form.mode === "daily_times") {
    payload.daily_times = parseDailyTimes(form.daily_times_text);
  } else {
    const intervalHours = Number(form.interval_hours);
    if (!Number.isInteger(intervalHours) || intervalHours <= 0) {
      throw new Error("Interval hours must be a positive integer.");
    }
    payload.interval_hours = intervalHours;
  }

  return payload;
}

function buildScheduleUpdatePayload(form: ScheduleFormState): FetchScheduleUpdate {
  const createPayload = buildSchedulePayload(form);
  return {
    enabled: createPayload.enabled,
    mode: createPayload.mode,
    daily_times: createPayload.daily_times,
    interval_hours: createPayload.interval_hours,
    timezone: createPayload.timezone,
  };
}

function buildScheduleFormFromExisting(schedule: FetchScheduleRead): ScheduleFormState {
  return {
    account_id: String(schedule.account_id),
    collector_instance_id: String(schedule.collector_instance_id),
    enabled: schedule.enabled,
    mode: schedule.mode,
    daily_times_text: schedule.daily_times?.join(",") ?? DEFAULT_DAILY_TIMES,
    interval_hours: schedule.interval_hours ? String(schedule.interval_hours) : DEFAULT_INTERVAL_HOURS,
    timezone: schedule.timezone,
  };
}

function buildScheduleSavedMessage(schedule: FetchScheduleRead): string {
  if (!schedule.enabled) {
    return "Schedule saved and currently paused.";
  }
  if (schedule.next_run_at) {
    return `Schedule saved. Next run: ${formatDateTime(schedule.next_run_at)}.`;
  }
  return "Schedule saved. Next run is being calculated.";
}

export function FetchSchedulesSection({
  accounts,
  instances,
  schedules,
  onScheduleChanged,
  onManualFetchChanged,
}: {
  accounts: AccountRead[];
  instances: InstanceRead[];
  schedules: FetchScheduleRead[];
  onScheduleChanged: () => Promise<void> | void;
  onManualFetchChanged: () => Promise<void> | void;
}) {
  const { pushToast } = useToast();
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [scheduleForm, setScheduleForm] = useState<ScheduleFormState>(() => buildInitialScheduleForm(accounts));
  const [manualForm, setManualForm] = useState<ManualFetchFormState>({
    account_id: "",
    collector_instance_id: "",
    report_date: new Date().toISOString().slice(0, 10),
  });

  useEffect(() => {
    setScheduleForm((current) => {
      if (current.account_id || accounts.length === 0) {
        return current;
      }
      return buildInitialScheduleForm(accounts);
    });
  }, [accounts]);

  const filteredScheduleInstances = useMemo(() => {
    if (!scheduleForm.account_id) {
      return [];
    }
    return instances.filter((instance) => String(instance.account_id) === scheduleForm.account_id);
  }, [instances, scheduleForm.account_id]);

  const filteredManualInstances = useMemo(() => {
    if (!manualForm.account_id) {
      return [];
    }
    return instances.filter((instance) => String(instance.account_id) === manualForm.account_id);
  }, [instances, manualForm.account_id]);

  const selectedSchedule = useMemo(
    () =>
      schedules.find(
        (schedule) =>
          String(schedule.account_id) === scheduleForm.account_id &&
          String(schedule.collector_instance_id) === scheduleForm.collector_instance_id,
      ) ?? null,
    [scheduleForm.account_id, scheduleForm.collector_instance_id, schedules],
  );

  const handleScheduleAccountChange = (accountId: string) => {
    const timezone = accounts.find((account) => String(account.id) === accountId)?.timezone ?? "Asia/Shanghai";
    setScheduleForm((current) => ({
      ...current,
      account_id: accountId,
      collector_instance_id: "",
      timezone,
    }));
  };

  const handleManualAccountChange = (accountId: string) => {
    setManualForm((current) => ({
      ...current,
      account_id: accountId,
      collector_instance_id: "",
    }));
  };

  const handleScheduleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);

    try {
      if (!scheduleForm.account_id || !scheduleForm.collector_instance_id) {
        throw new Error("Please select both account and instance.");
      }

      let savedSchedule: FetchScheduleRead;
      if (selectedSchedule) {
        savedSchedule = await api.updateFetchSchedule(selectedSchedule.id, buildScheduleUpdatePayload(scheduleForm));
        pushToast({
          title: "Schedule updated",
          message: buildScheduleSavedMessage(savedSchedule),
          tone: "success",
        });
      } else {
        savedSchedule = await api.createFetchSchedule(buildSchedulePayload(scheduleForm));
        pushToast({
          title: "Schedule created",
          message: buildScheduleSavedMessage(savedSchedule),
          tone: "success",
        });
      }

    } catch (error) {
      pushToast({ title: "Failed to save schedule", message: getErrorMessage(error as ApiError), tone: "error" });
      setSaving(false);
      return;
    }
    try {
      await onScheduleChanged();
    } catch {
      // The resource loader owns the single refresh-failure toast.
    } finally {
      setSaving(false);
    }
  };

  const handleManualFetch = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRunning(true);

    try {
      if (!manualForm.account_id || !manualForm.collector_instance_id) {
        throw new Error("Please select both account and instance.");
      }

      const result = await api.triggerManualFetch({
        account_id: Number(manualForm.account_id),
        collector_instance_id: Number(manualForm.collector_instance_id),
        report_date: manualForm.report_date,
      });

      const syncMessage =
        result.hourly_sync_task_id != null
          ? ` Hourly sync task #${result.hourly_sync_task_id} is ${result.hourly_sync_task_status ?? "pending"}.`
          : "";

      pushToast({
        title: "Manual fetch accepted",
        message: `${result.message ?? result.request_id ?? result.status ?? "fetch.php accepted the request."}${syncMessage}`,
        tone: "success",
      });
    } catch (error) {
      pushToast({ title: "Manual fetch failed", message: getErrorMessage(error as ApiError), tone: "error" });
      setRunning(false);
      return;
    }
    try {
      await onManualFetchChanged();
    } catch {
      // Invalidation is local, but keep callback failures distinct from mutation failures.
    } finally {
      setRunning(false);
    }
  };

  const loadScheduleIntoForm = (schedule: FetchScheduleRead) => {
    setScheduleForm(buildScheduleFormFromExisting(schedule));
    setManualForm((current) => ({
      ...current,
      account_id: String(schedule.account_id),
      collector_instance_id: String(schedule.collector_instance_id),
    }));
  };

  return (
    <SectionCard
      title="Fetch Control"
      description="Configure recurring fetch schedules and trigger the real node fetch.php chain immediately when needed."
    >
      <div className="two-column">
        <div className="stack-panel">
          <form className="form-grid" onSubmit={handleScheduleSubmit}>
            <Field
              label="Account"
              as="select"
              selectProps={{
                value: scheduleForm.account_id,
                onChange: (event) => handleScheduleAccountChange(event.target.value),
                required: true,
              }}
            >
              <option value="">Select an account</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.id} - {account.name}
                </option>
              ))}
            </Field>

            <Field
              label="Instance"
              as="select"
              selectProps={{
                value: scheduleForm.collector_instance_id,
                onChange: (event) => setScheduleForm((current) => ({ ...current, collector_instance_id: event.target.value })),
                required: true,
                disabled: !scheduleForm.account_id,
              }}
            >
              <option value="">Select an instance</option>
              {filteredScheduleInstances.map((instance) => (
                <option key={instance.id} value={instance.id}>
                  {instance.id} - {instance.name}
                </option>
              ))}
            </Field>

            <div className="inline-fields">
              <Field
                label="Enabled"
                as="select"
                selectProps={{
                  value: scheduleForm.enabled ? "true" : "false",
                  onChange: (event) => setScheduleForm((current) => ({ ...current, enabled: event.target.value === "true" })),
                }}
              >
                <option value="true">enabled</option>
                <option value="false">disabled</option>
              </Field>

              <Field
                label="Mode"
                as="select"
                selectProps={{
                  value: scheduleForm.mode,
                  onChange: (event) =>
                    setScheduleForm((current) => ({ ...current, mode: event.target.value as FetchScheduleMode })),
                }}
              >
                <option value="daily_times">daily_times</option>
                <option value="interval_hours">interval_hours</option>
              </Field>
            </div>

            <Field
              label="Timezone"
              hint="Use an IANA timezone, for example Asia/Shanghai or America/Los_Angeles."
              inputProps={{
                value: scheduleForm.timezone,
                onChange: (event) => setScheduleForm((current) => ({ ...current, timezone: event.target.value })),
                required: true,
              }}
            />

            {scheduleForm.mode === "daily_times" ? (
              <Field
                label="Daily times"
                hint="Comma-separated HH:MM values. Example: 08:00,20:00"
                inputProps={{
                  value: scheduleForm.daily_times_text,
                  onChange: (event) => setScheduleForm((current) => ({ ...current, daily_times_text: event.target.value })),
                  required: true,
                }}
              />
            ) : (
              <Field
                label="Interval hours"
                hint="Positive integer. The scheduler will re-run after this many hours."
                inputProps={{
                  type: "number",
                  min: 1,
                  step: 1,
                  value: scheduleForm.interval_hours,
                  onChange: (event) => setScheduleForm((current) => ({ ...current, interval_hours: event.target.value })),
                  required: true,
                }}
              />
            )}

            {selectedSchedule ? (
              <div className="schedule-preview">
                <div className="schedule-preview-row">
                  <span>Next run</span>
                  <strong>{selectedSchedule.enabled ? formatDateTime(selectedSchedule.next_run_at) : "Paused"}</strong>
                </div>
                <div className="schedule-preview-row">
                  <span>Last trigger</span>
                  <strong>{formatDateTime(selectedSchedule.last_triggered_at)}</strong>
                </div>
                <div className="schedule-preview-row">
                  <span>Last result</span>
                  <strong>{formatNullable(selectedSchedule.last_trigger_message ?? selectedSchedule.last_trigger_status)}</strong>
                </div>
              </div>
            ) : null}

            <div className="button-row">
              <button type="submit" className="primary-button" disabled={saving}>
                {saving ? "Saving..." : selectedSchedule ? "Update Schedule" : "Create Schedule"}
              </button>
            </div>
          </form>

          <form className="form-grid" onSubmit={handleManualFetch}>
            <h3 className="subsection-title">Immediate Fetch</h3>

            <Field
              label="Account"
              as="select"
              selectProps={{
                value: manualForm.account_id,
                onChange: (event) => handleManualAccountChange(event.target.value),
                required: true,
              }}
            >
              <option value="">Select an account</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.id} - {account.name}
                </option>
              ))}
            </Field>

            <Field
              label="Instance"
              as="select"
              selectProps={{
                value: manualForm.collector_instance_id,
                onChange: (event) => setManualForm((current) => ({ ...current, collector_instance_id: event.target.value })),
                required: true,
                disabled: !manualForm.account_id,
              }}
            >
              <option value="">Select an instance</option>
              {filteredManualInstances.map((instance) => (
                <option key={instance.id} value={instance.id}>
                  {instance.id} - {instance.name}
                </option>
              ))}
            </Field>

            <Field
              label="Report date"
              inputProps={{
                type: "date",
                value: manualForm.report_date,
                onChange: (event) => setManualForm((current) => ({ ...current, report_date: event.target.value })),
                required: true,
              }}
            />

            <div className="button-row">
              <button type="submit" className="primary-button" disabled={running}>
                {running ? "Triggering..." : "Run Fetch Now"}
              </button>
            </div>
          </form>
        </div>

        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Account</th>
                <th>Instance</th>
                <th>Mode</th>
                <th>Status</th>
                <th>Next run</th>
                <th>Last result</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((schedule) => (
                <tr key={schedule.id}>
                  <td>{schedule.id}</td>
                  <td>{schedule.account_id}</td>
                  <td>{schedule.collector_instance_id}</td>
                  <td>
                    <div>{schedule.mode}</div>
                    <small className="table-meta">
                      {schedule.mode === "daily_times"
                        ? schedule.daily_times?.join(", ") ?? "-"
                        : `${schedule.interval_hours ?? "-"}h`}
                    </small>
                  </td>
                  <td>
                    <StatusBadge value={schedule.enabled ? "enabled" : "disabled"} />
                    <div className="table-meta">{schedule.enabled ? "Scheduled" : "Paused"}</div>
                  </td>
                  <td>{schedule.enabled ? formatDateTime(schedule.next_run_at) : "Paused"}</td>
                  <td>
                    <div>{formatNullable(schedule.last_trigger_status)}</div>
                    <small className="table-meta">{formatNullable(schedule.last_trigger_message)}</small>
                  </td>
                  <td>
                    <button type="button" className="link-button" onClick={() => loadScheduleIntoForm(schedule)}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
              {schedules.length === 0 ? (
                <tr>
                  <td colSpan={8} className="empty-cell">
                    No fetch schedules yet. Create one to enable planned fetch, or use immediate fetch on the left.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </SectionCard>
  );
}
