import { useMemo, useState } from "react";

import { api, type ApiError } from "../../lib/api";
import { getErrorMessage } from "../../lib/errorMessages";
import { formatDateTime, formatNullable } from "../../lib/format";
import { buildInstanceOnboardingNote } from "../../lib/operatorGuidance";
import { SectionCard } from "../../components/ui/SectionCard";
import { Field } from "../../components/ui/Field";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { CopyButton } from "../../components/ui/CopyButton";
import { useToast } from "../../components/ui/useToast";
import type { AccountRead, InstanceProvisionResponse, InstanceRead } from "../../types/api";

export function InstancesSection({
  accounts,
  instances,
  onChanged,
}: {
  accounts: AccountRead[];
  instances: InstanceRead[];
  onChanged: () => Promise<void> | void;
}) {
  const { pushToast } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [createdInstance, setCreatedInstance] = useState<InstanceProvisionResponse | null>(null);
  const [form, setForm] = useState({
    account_id: "",
    name: "",
    status: "provisioning",
    expected_egress_ip: "",
    report_base_url: "",
    report_account_key: "",
    report_token: "",
  });

  const selectedAccount = useMemo(
    () => accounts.find((account) => String(account.id) === form.account_id) ?? null,
    [accounts, form.account_id],
  );

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      const result = await api.createInstance({
        account_id: Number(form.account_id),
        name: form.name.trim(),
        status: form.status as "provisioning" | "ready" | "blocked" | "offline",
        expected_egress_ip: form.expected_egress_ip.trim() || null,
        report_base_url: form.report_base_url.trim() || null,
        report_account_key: form.report_account_key.trim() || null,
        report_token: form.report_token.trim() || null,
      });
      setCreatedInstance(result);
      pushToast({
        title: "Instance created",
        message: "The instance token is only shown once. Copy it before starting the collector node.",
        tone: "success",
      });
      setForm({
        account_id: "",
        name: "",
        status: "provisioning",
        expected_egress_ip: "",
        report_base_url: "",
        report_account_key: "",
        report_token: "",
      });
      await onChanged();
    } catch (error) {
      pushToast({ title: "Failed to create instance", message: getErrorMessage(error as ApiError), tone: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SectionCard
      title="Instances"
      description="Register the execution node itself and fill in the remote report settings used by the mid-platform reader."
    >
      <div className="two-column">
        <form className="form-grid" onSubmit={handleSubmit}>
          <p className="field-hint">{buildInstanceOnboardingNote()}</p>

          <Field
            label="Account"
            as="select"
            selectProps={{
              value: form.account_id,
              onChange: (event) => setForm((current) => ({ ...current, account_id: event.target.value })),
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
            label="Instance Name"
            hint={selectedAccount ? `Keep it aligned with the account or host name, for example ${selectedAccount.name}-node.` : undefined}
            inputProps={{
              value: form.name,
              onChange: (event) => setForm((current) => ({ ...current, name: event.target.value })),
              required: true,
            }}
          />

          <Field
            label="Instance Status"
            as="select"
            selectProps={{
              value: form.status,
              onChange: (event) => setForm((current) => ({ ...current, status: event.target.value })),
            }}
          >
            <option value="provisioning">provisioning</option>
            <option value="ready">ready</option>
            <option value="blocked">blocked</option>
            <option value="offline">offline</option>
          </Field>

          <Field
            label="Expected Egress IP"
            hint="If the node uses a fixed proxy, record the expected outbound IP here."
            inputProps={{
              value: form.expected_egress_ip,
              onChange: (event) => setForm((current) => ({ ...current, expected_egress_ip: event.target.value })),
            }}
          />

          <Field
            label="Report Base URL"
            hint="The mid-platform will read this node through /ke/report.php, for example https://api.example.com."
            inputProps={{
              value: form.report_base_url,
              onChange: (event) => setForm((current) => ({ ...current, report_base_url: event.target.value })),
            }}
          />

          <Field
            label="Node account_key"
            hint="This should match the account_key used by the node's fetch.php and report.php."
            inputProps={{
              value: form.report_account_key,
              onChange: (event) => setForm((current) => ({ ...current, report_account_key: event.target.value })),
            }}
          />

          <Field
            label="Node report token"
            hint="Used only when the mid-platform reads snapshots from this node. It will not be shown again in the list."
            inputProps={{
              type: "password",
              value: form.report_token,
              onChange: (event) => setForm((current) => ({ ...current, report_token: event.target.value })),
            }}
          />

          <button type="submit" className="primary-button" disabled={submitting}>
            {submitting ? "Creating..." : "Create Instance"}
          </button>
        </form>

        <div className="stack-panel">
          {createdInstance ? (
            <div className="token-panel">
              <div className="token-panel-header">
                <strong>Provision Result</strong>
                <CopyButton value={createdInstance.instance_token} label="Copy Token" />
              </div>
              <p>Instance ID: {createdInstance.id}</p>
              <textarea readOnly className="token-value" value={createdInstance.instance_token} />
              <p className="token-meta">The instance token is displayed only once. Save it before launching the collector node.</p>
            </div>
          ) : null}

          <div className="table-card">
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Account</th>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Node Report Access</th>
                  <th>Expected Egress</th>
                  <th>Last Heartbeat</th>
                </tr>
              </thead>
              <tbody>
                {instances.map((instance) => (
                  <tr key={instance.id}>
                    <td>{instance.id}</td>
                    <td>{instance.account_id}</td>
                    <td>{instance.name}</td>
                    <td>
                      <StatusBadge value={instance.status} />
                    </td>
                    <td>
                      {instance.report_base_url ? (
                        <>
                          <div>{instance.report_base_url}</div>
                          <small className="table-meta">
                            {instance.report_account_key ? `account_key=${instance.report_account_key}` : "Missing account_key"}
                            {" | "}
                            {instance.report_token_present ? "token configured" : "token missing"}
                          </small>
                        </>
                      ) : (
                        <span className="table-meta">Not configured</span>
                      )}
                    </td>
                    <td>{formatNullable(instance.expected_egress_ip)}</td>
                    <td>{formatDateTime(instance.last_heartbeat_at)}</td>
                  </tr>
                ))}
                {instances.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="empty-cell">
                      No instances yet. Create one node per account.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </SectionCard>
  );
}
