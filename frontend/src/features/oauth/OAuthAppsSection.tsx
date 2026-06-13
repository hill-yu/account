import { useMemo, useState } from "react";

import { SectionCard } from "../../components/ui/SectionCard";
import { Field } from "../../components/ui/Field";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { CopyButton } from "../../components/ui/CopyButton";
import { useToast } from "../../components/ui/useToast";
import { api, type ApiError } from "../../lib/api";
import { getErrorMessage } from "../../lib/errorMessages";
import { formatDateTime } from "../../lib/format";
import { buildOAuthCallbackRedirectUri } from "../../lib/oauth";
import {
  buildOAuthRedirectUriHint,
  buildSecondAccountChecklist,
} from "../../lib/operatorGuidance";
import type { AccountRead, AuthorizationUrlResponse, OAuthAppRead } from "../../types/api";

export function OAuthAppsSection({
  accounts,
  oauthApps,
  onChanged,
}: {
  accounts: AccountRead[];
  oauthApps: OAuthAppRead[];
  onChanged: () => Promise<void> | void;
}) {
  const { pushToast } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [generatingId, setGeneratingId] = useState<number | null>(null);
  const [generatedUrl, setGeneratedUrl] = useState<AuthorizationUrlResponse | null>(null);
  const checklist = buildSecondAccountChecklist();
  const defaultRedirectUri = useMemo(() => {
    if (typeof window === "undefined") {
      return "http://127.0.0.1:4173/oauth/google/callback";
    }
    return buildOAuthCallbackRedirectUri(window.location.origin);
  }, []);
  const [form, setForm] = useState({
    account_id: "",
    client_id: "",
    client_secret: "",
    redirect_uri: defaultRedirectUri,
    scopes: "https://www.googleapis.com/auth/dfp",
    app_status: "active",
    verification_status: "pending",
  });

  const handleCreate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await api.createOAuthApp({
        account_id: Number(form.account_id),
        client_id: form.client_id.trim(),
        client_secret: form.client_secret.trim(),
        redirect_uri: form.redirect_uri.trim(),
        scopes: form.scopes.trim(),
        app_status: form.app_status as "pending" | "active" | "disabled",
        verification_status: form.verification_status as "pending" | "verified" | "rejected",
      });
      pushToast({ title: "OAuth app created", tone: "success" });
      setForm((current) => ({ ...current, client_id: "", client_secret: "" }));
      await onChanged();
    } catch (error) {
      pushToast({ title: "Failed to create OAuth app", message: getErrorMessage(error as ApiError), tone: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  const handleGenerate = async (oauthAppId: number) => {
    setGeneratingId(oauthAppId);
    try {
      const result = await api.generateAuthorizationUrl(oauthAppId);
      setGeneratedUrl(result);
      pushToast({ title: "Authorization URL generated", tone: "success" });
    } catch (error) {
      pushToast({
        title: "Failed to generate authorization URL",
        message: getErrorMessage(error as ApiError),
        tone: "error",
      });
    } finally {
      setGeneratingId(null);
    }
  };

  return (
    <SectionCard
      title="OAuth Apps"
      description="Create one OAuth app per account and keep each account pointed at its own website callback."
    >
      <div className="two-column">
        <form className="form-grid" onSubmit={handleCreate}>
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
            label="Client ID"
            inputProps={{
              value: form.client_id,
              onChange: (event) => setForm((current) => ({ ...current, client_id: event.target.value })),
              required: true,
            }}
          />
          <Field
            label="Client Secret"
            inputProps={{
              type: "password",
              value: form.client_secret,
              onChange: (event) => setForm((current) => ({ ...current, client_secret: event.target.value })),
              required: true,
            }}
          />
          <Field
            label="Redirect URI"
            hint={buildOAuthRedirectUriHint()}
            inputProps={{
              value: form.redirect_uri,
              onChange: (event) => setForm((current) => ({ ...current, redirect_uri: event.target.value })),
              required: true,
            }}
          />
          <Field
            label="Scopes"
            inputProps={{
              value: form.scopes,
              onChange: (event) => setForm((current) => ({ ...current, scopes: event.target.value })),
              required: true,
            }}
          />
          <div className="inline-fields">
            <Field
              label="App Status"
              as="select"
              selectProps={{
                value: form.app_status,
                onChange: (event) => setForm((current) => ({ ...current, app_status: event.target.value })),
              }}
            >
              <option value="active">active</option>
              <option value="pending">pending</option>
              <option value="disabled">disabled</option>
            </Field>
            <Field
              label="Verification"
              as="select"
              selectProps={{
                value: form.verification_status,
                onChange: (event) => setForm((current) => ({ ...current, verification_status: event.target.value })),
              }}
            >
              <option value="pending">pending</option>
              <option value="verified">verified</option>
              <option value="rejected">rejected</option>
            </Field>
          </div>
          <button type="submit" className="primary-button" disabled={submitting}>
            {submitting ? "Creating..." : "Create OAuth App"}
          </button>
        </form>

        <div className="stack-panel">
          <div className="token-panel">
            <div className="token-panel-header">
              <strong>Second Account Checklist</strong>
            </div>
            <ul className="meta-list">
              {checklist.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>

          {generatedUrl ? (
            <div className="token-panel">
              <div className="token-panel-header">
                <strong>Authorization URL</strong>
                <CopyButton value={generatedUrl.authorization_url} />
              </div>
              <textarea readOnly className="token-value" value={generatedUrl.authorization_url} />
              <div className="token-actions">
                <a className="secondary-button link-button" href={generatedUrl.authorization_url} target="_blank" rel="noreferrer">
                  Open
                </a>
                <span className="token-meta">State expires at: {formatDateTime(generatedUrl.state_expires_at)}</span>
              </div>
            </div>
          ) : null}

          <div className="table-card">
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Account</th>
                  <th>Client ID</th>
                  <th>Redirect URI</th>
                  <th>Authorization</th>
                  <th>Refresh Token</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {oauthApps.map((oauthApp) => (
                  <tr key={oauthApp.id}>
                    <td>{oauthApp.id}</td>
                    <td>{oauthApp.account_id}</td>
                    <td>{oauthApp.client_id}</td>
                    <td>
                      <div>{oauthApp.redirect_uri}</div>
                    </td>
                    <td>
                      <StatusBadge value={oauthApp.authorization_status} />
                    </td>
                    <td>{oauthApp.refresh_token_present ? "Present" : "Missing"}</td>
                    <td>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => void handleGenerate(oauthApp.id)}
                        disabled={generatingId === oauthApp.id}
                      >
                        {generatingId === oauthApp.id ? "Generating..." : "Generate URL"}
                      </button>
                    </td>
                  </tr>
                ))}
                {oauthApps.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="empty-cell">
                      No OAuth apps yet. Create one per account and verify the redirect URI before authorizing.
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
