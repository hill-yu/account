import { useState } from "react";

import { api, type ApiError } from "../../lib/api";
import { getErrorMessage } from "../../lib/errorMessages";
import { formatDateTime, formatNullable } from "../../lib/format";
import { SectionCard } from "../../components/ui/SectionCard";
import { Field } from "../../components/ui/Field";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { useToast } from "../../components/ui/useToast";
import type { AccountRead, InstanceRead, SyncTaskRead } from "../../types/api";

export function TasksSection({
  accounts,
  instances,
  tasks,
  onChanged,
}: {
  accounts: AccountRead[];
  instances: InstanceRead[];
  tasks: SyncTaskRead[];
  onChanged: () => Promise<void> | void;
}) {
  const { pushToast } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    account_id: "",
    collector_instance_id: "",
    report_date: new Date().toISOString().slice(0, 10),
    task_type: "report_fetch",
    status: "pending",
    external_request_id: "",
  });

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await api.createTask({
        account_id: Number(form.account_id),
        collector_instance_id: Number(form.collector_instance_id),
        report_date: form.report_date,
        task_type: form.task_type,
        status: form.status as "pending" | "in_progress" | "succeeded" | "failed" | "cancelled" | "blocked",
        external_request_id: form.external_request_id.trim() || null,
      });
      pushToast({ title: "同步任务已创建", tone: "success" });
      setForm((current) => ({ ...current, external_request_id: "" }));
      await onChanged();
    } catch (error) {
      pushToast({ title: "创建任务失败", message: getErrorMessage(error as ApiError), tone: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SectionCard title="Tasks" description="手动创建按日同步任务，并查看最近任务状态。">
      <div className="two-column">
        <form className="form-grid" onSubmit={handleSubmit}>
          <Field
            label="账号"
            as="select"
            selectProps={{ value: form.account_id, onChange: (event) => setForm((current) => ({ ...current, account_id: event.target.value })), required: true }}
          >
            <option value="">请选择账号</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.id} - {account.name}
              </option>
            ))}
          </Field>
          <Field
            label="实例"
            as="select"
            selectProps={{
              value: form.collector_instance_id,
              onChange: (event) => setForm((current) => ({ ...current, collector_instance_id: event.target.value })),
              required: true,
            }}
          >
            <option value="">请选择实例</option>
            {instances.map((instance) => (
              <option key={instance.id} value={instance.id}>
                {instance.id} - {instance.name}
              </option>
            ))}
          </Field>
          <Field
            label="日期"
            inputProps={{ type: "date", value: form.report_date, onChange: (event) => setForm((current) => ({ ...current, report_date: event.target.value })), required: true }}
          />
          <Field label="Task Type" inputProps={{ value: form.task_type, onChange: (event) => setForm((current) => ({ ...current, task_type: event.target.value })), required: true }} />
          <Field
            label="初始状态"
            as="select"
            selectProps={{ value: form.status, onChange: (event) => setForm((current) => ({ ...current, status: event.target.value })) }}
          >
            <option value="pending">pending</option>
            <option value="blocked">blocked</option>
            <option value="cancelled">cancelled</option>
          </Field>
          <Field label="External Request ID" inputProps={{ value: form.external_request_id, onChange: (event) => setForm((current) => ({ ...current, external_request_id: event.target.value })) }} />
          <button type="submit" className="primary-button" disabled={submitting}>
            {submitting ? "创建中..." : "Create Task"}
          </button>
        </form>

        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>账号</th>
                <th>实例</th>
                <th>日期</th>
                <th>状态</th>
                <th>开始时间</th>
                <th>请求 ID</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id}>
                  <td>{task.id}</td>
                  <td>{task.account_id}</td>
                  <td>{task.collector_instance_id}</td>
                  <td>{task.report_date}</td>
                  <td>
                    <StatusBadge value={task.status} />
                  </td>
                  <td>{formatDateTime(task.started_at)}</td>
                  <td>{formatNullable(task.external_request_id)}</td>
                </tr>
              ))}
              {tasks.length === 0 ? (
                <tr>
                  <td colSpan={7} className="empty-cell">
                    暂无任务，请先创建一个按日同步任务。
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
