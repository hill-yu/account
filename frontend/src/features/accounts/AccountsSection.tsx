import { useState } from "react";

import { api, type ApiError } from "../../lib/api";
import { getErrorMessage } from "../../lib/errorMessages";
import { formatDateTime, formatNullable } from "../../lib/format";
import { SectionCard } from "../../components/ui/SectionCard";
import { Field } from "../../components/ui/Field";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { useToast } from "../../components/ui/useToast";
import type { AccountRead } from "../../types/api";

export function AccountsSection({ accounts, onChanged }: { accounts: AccountRead[]; onChanged: () => Promise<void> | void }) {
  const { pushToast } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    name: "",
    external_account_id: "",
    status: "active",
  });

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await api.createAccount({
        name: form.name.trim(),
        external_account_id: form.external_account_id.trim() || null,
        status: form.status as "pending" | "active" | "disabled",
      });
      pushToast({ title: "账号已创建", tone: "success" });
      setForm({ name: "", external_account_id: "", status: "active" });
      await onChanged();
    } catch (error) {
      pushToast({ title: "创建账号失败", message: getErrorMessage(error as ApiError), tone: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SectionCard title="Accounts" description="创建中台账号记录，并维护可选的 AdSense/AdX network code。">
      <div className="two-column">
        <form className="form-grid" onSubmit={handleSubmit}>
          <Field label="账号名称" inputProps={{ value: form.name, onChange: (event) => setForm((current) => ({ ...current, name: event.target.value })), required: true }} />
          <Field
            label="Network Code"
            hint="可选。当前会把 external_account_id 作为 network code 保存。"
            inputProps={{ value: form.external_account_id, onChange: (event) => setForm((current) => ({ ...current, external_account_id: event.target.value })) }}
          />
          <Field
            label="状态"
            as="select"
            selectProps={{ value: form.status, onChange: (event) => setForm((current) => ({ ...current, status: event.target.value })) }}
          >
            <option value="active">active</option>
            <option value="pending">pending</option>
            <option value="disabled">disabled</option>
          </Field>
          <button type="submit" className="primary-button" disabled={submitting}>
            {submitting ? "创建中..." : "Create Account"}
          </button>
        </form>

        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>名称</th>
                <th>Network</th>
                <th>状态</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => (
                <tr key={account.id}>
                  <td>{account.id}</td>
                  <td>{account.name}</td>
                  <td>{formatNullable(account.external_account_id)}</td>
                  <td><StatusBadge value={account.status} /></td>
                  <td>{formatDateTime(account.created_at)}</td>
                </tr>
              ))}
              {accounts.length === 0 ? (
                <tr>
                  <td colSpan={5} className="empty-cell">当前还没有任何账号记录。</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </SectionCard>
  );
}
