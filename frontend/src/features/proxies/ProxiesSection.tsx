import { useState } from "react";

import { api, type ApiError } from "../../lib/api";
import { getErrorMessage } from "../../lib/errorMessages";
import { SectionCard } from "../../components/ui/SectionCard";
import { Field } from "../../components/ui/Field";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { useToast } from "../../components/ui/useToast";
import type { AccountRead, InstanceRead, ProxyBindingRead } from "../../types/api";

export function ProxiesSection({
  accounts,
  instances,
  proxies,
  onChanged,
}: {
  accounts: AccountRead[];
  instances: InstanceRead[];
  proxies: ProxyBindingRead[];
  onChanged: () => Promise<void> | void;
}) {
  const { pushToast } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    account_id: "",
    collector_instance_id: "",
    provider_name: "",
    protocol: "http",
    host: "",
    port: "8080",
    username: "",
    password: "",
    expected_egress_ip: "",
    status: "active",
  });

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await api.createProxy({
        account_id: Number(form.account_id),
        collector_instance_id: Number(form.collector_instance_id),
        provider_name: form.provider_name.trim(),
        protocol: form.protocol as "http" | "https" | "socks5",
        host: form.host.trim(),
        port: Number(form.port),
        username: form.username.trim() || null,
        password: form.password.trim() || null,
        expected_egress_ip: form.expected_egress_ip.trim(),
        status: form.status as "active" | "disabled" | "error",
      });
      pushToast({ title: "代理绑定已创建", tone: "success" });
      setForm({
        account_id: "",
        collector_instance_id: "",
        provider_name: "",
        protocol: "http",
        host: "",
        port: "8080",
        username: "",
        password: "",
        expected_egress_ip: "",
        status: "active",
      });
      await onChanged();
    } catch (error) {
      pushToast({ title: "创建代理绑定失败", message: getErrorMessage(error as ApiError), tone: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SectionCard title="Proxies" description="固定绑定实例的代理出口。collector 执行前会校验出口 IP，不一致会直接阻塞任务。">
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
          <Field label="Provider" inputProps={{ value: form.provider_name, onChange: (event) => setForm((current) => ({ ...current, provider_name: event.target.value })), required: true }} />
          <div className="inline-fields">
            <Field
              label="Protocol"
              as="select"
              selectProps={{ value: form.protocol, onChange: (event) => setForm((current) => ({ ...current, protocol: event.target.value })) }}
            >
              <option value="http">http</option>
              <option value="https">https</option>
              <option value="socks5">socks5</option>
            </Field>
            <Field
              label="Port"
              inputProps={{ type: "number", value: form.port, onChange: (event) => setForm((current) => ({ ...current, port: event.target.value })), required: true }}
            />
          </div>
          <Field label="Host" inputProps={{ value: form.host, onChange: (event) => setForm((current) => ({ ...current, host: event.target.value })), required: true }} />
          <Field label="Username" inputProps={{ value: form.username, onChange: (event) => setForm((current) => ({ ...current, username: event.target.value })) }} />
          <Field label="Password" inputProps={{ type: "password", value: form.password, onChange: (event) => setForm((current) => ({ ...current, password: event.target.value })) }} />
          <Field label="出口 IP" inputProps={{ value: form.expected_egress_ip, onChange: (event) => setForm((current) => ({ ...current, expected_egress_ip: event.target.value })), required: true }} />
          <Field
            label="状态"
            as="select"
            selectProps={{ value: form.status, onChange: (event) => setForm((current) => ({ ...current, status: event.target.value })) }}
          >
            <option value="active">active</option>
            <option value="disabled">disabled</option>
            <option value="error">error</option>
          </Field>
          <button type="submit" className="primary-button" disabled={submitting}>
            {submitting ? "创建中..." : "Create Proxy Binding"}
          </button>
        </form>

        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>账号</th>
                <th>实例</th>
                <th>代理</th>
                <th>出口 IP</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {proxies.map((proxy) => (
                <tr key={proxy.id}>
                  <td>{proxy.id}</td>
                  <td>{proxy.account_id}</td>
                  <td>{proxy.collector_instance_id}</td>
                  <td>
                    {proxy.provider_name} ({proxy.protocol})
                  </td>
                  <td>{proxy.expected_egress_ip}</td>
                  <td>
                    <StatusBadge value={proxy.status} />
                  </td>
                </tr>
              ))}
              {proxies.length === 0 ? (
                <tr>
                  <td colSpan={6} className="empty-cell">
                    暂无代理绑定，请先为实例配置一个固定代理。
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
