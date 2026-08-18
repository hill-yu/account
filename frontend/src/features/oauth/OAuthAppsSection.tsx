import { useState } from "react";

import { SectionCard } from "../../components/ui/SectionCard";
import { Field } from "../../components/ui/Field";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { CopyButton } from "../../components/ui/CopyButton";
import { useToast } from "../../components/ui/useToast";
import { api, type ApiError } from "../../lib/api";
import { getErrorMessage } from "../../lib/errorMessages";
import { formatDateTime } from "../../lib/format";
import { parseOAuthCallbackImportJson } from "../../lib/oauth";
import {
  buildOAuthJsonImportHint,
  buildOAuthRedirectUriHint,
  buildSecondAccountChecklist,
  getOAuthAuthorizationAction,
  shortenCredentialFingerprint,
} from "../../lib/operatorGuidance";
import type { AccountRead, AuthorizationUrlResponse, OAuthAppRead, OAuthCallbackImportRequest } from "../../types/api";

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
  const [importing, setImporting] = useState(false);
  const [generatedUrl, setGeneratedUrl] = useState<AuthorizationUrlResponse | null>(null);
  const [selectedImportFileName, setSelectedImportFileName] = useState("");
  const [importPayload, setImportPayload] = useState<OAuthCallbackImportRequest | null>(null);
  const checklist = buildSecondAccountChecklist();
  const [form, setForm] = useState({
    account_id: "",
    client_id: "",
    client_secret: "",
    redirect_uri: "",
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
    } catch (error) {
      pushToast({ title: "Failed to create OAuth app", message: getErrorMessage(error as ApiError), tone: "error" });
      setSubmitting(false);
      return;
    }
    try {
      await onChanged();
    } catch {
      // The resource loader owns the single refresh-failure toast.
    } finally {
      setSubmitting(false);
    }
  };

  const handleGenerate = async (oauthApp: OAuthAppRead) => {
    const action = getOAuthAuthorizationAction(oauthApp.flow_status, oauthApp.runtime_status);
    if (action.disabled) {
      return;
    }
    let reason: string | undefined;
    if (action.requiresConfirmation) {
      const confirmed = window.confirm("Reauthorizing can replace the current credential. Continue?");
      if (!confirmed) {
        return;
      }
      reason = window.prompt("Reason for reauthorization")?.trim() || undefined;
      if (!reason) {
        pushToast({ title: "Reauthorization reason required", tone: "error" });
        return;
      }
    } else if (action.forceReauthorize) {
      reason = "restore_revoked_credential";
    }
    setGeneratingId(oauthApp.id);
    try {
      const result = await api.generateAuthorizationUrl(
        oauthApp.id,
        action.forceReauthorize ? { force_reauthorize: true, reason } : undefined,
      );
      setGeneratedUrl(result);
      pushToast({ title: "Authorization URL generated", tone: "success" });
    } catch (error) {
      pushToast({
        title: "Failed to generate authorization URL",
        message: getErrorMessage(error as ApiError),
        tone: "error",
      });
      setGeneratingId(null);
      return;
    }
    try {
      await onChanged();
    } catch {
      // The resource loader reports refresh failures.
    } finally {
      setGeneratingId(null);
    }
  };

  const handleImportFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      setSelectedImportFileName("");
      setImportPayload(null);
      return;
    }

    try {
      const text = await file.text();
      const parsed = parseOAuthCallbackImportJson(text);
      setSelectedImportFileName(file.name);
      setImportPayload(parsed);
      pushToast({ title: "Callback JSON loaded", tone: "success" });
    } catch (error) {
      setSelectedImportFileName(file.name);
      setImportPayload(null);
      pushToast({
        title: "Invalid callback JSON",
        message: error instanceof Error ? error.message : "The selected file could not be parsed.",
        tone: "error",
      });
    } finally {
      event.target.value = "";
    }
  };

  const handleImport = async () => {
    if (!importPayload) {
      pushToast({ title: "No callback JSON loaded", message: "Choose a callback JSON file first.", tone: "error" });
      return;
    }

    setImporting(true);
    try {
      const result = await api.importOAuthCallbackJson(importPayload);
      pushToast({
        title: "Callback JSON imported",
        message: `OAuth app ${result.oauth_app_id} is now ${result.authorization_status}.`,
        tone: "success",
      });
      setSelectedImportFileName("");
      setImportPayload(null);
    } catch (error) {
      pushToast({
        title: "Failed to import callback JSON",
        message: getErrorMessage(error as ApiError),
        tone: "error",
      });
      setImporting(false);
      return;
    }
    try {
      await onChanged();
    } catch {
      // The resource loader owns the single refresh-failure toast.
    } finally {
      setImporting(false);
    }
  };

  return (
    <SectionCard
      title="OAuth Apps"
      description="Create one OAuth app per account, point it at that account's own website callback, and import callback JSON here in the control plane."
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
              placeholder: "https://account-site.example.com/oauth/google/callback",
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
              <p className="token-meta">{buildOAuthJsonImportHint()}</p>
            </div>
          ) : null}

          <div className="token-panel">
            <div className="token-panel-header">
              <strong>Import Callback JSON</strong>
            </div>
            <p className="token-meta">
              Upload the JSON downloaded from the account website callback page. This onboarding step belongs to the control plane only.
            </p>
            <input type="file" accept="application/json,.json" onChange={(event) => void handleImportFileChange(event)} />
            {importPayload ? (
              <ul className="meta-list">
                <li>File: {selectedImportFileName}</li>
                <li>Redirect URI: {importPayload.redirect_uri}</li>
                <li>State: {importPayload.state}</li>
                <li>Callback URL: {importPayload.callback_url}</li>
              </ul>
            ) : selectedImportFileName ? (
              <p className="token-meta">Loaded file: {selectedImportFileName}</p>
            ) : null}
            <div className="token-actions">
              <button type="button" className="primary-button" disabled={!importPayload || importing} onClick={() => void handleImport()}>
                {importing ? "Importing..." : "Import Callback JSON"}
              </button>
            </div>
          </div>

          <div className="table-card oauth-apps-table-card">
            <table className="data-table oauth-apps-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Account / App</th>
                  <th>Flow</th>
                  <th>Runtime</th>
                  <th>Credential</th>
                  <th>Failure</th>
                  <th>Verified</th>
                  <th>Next action</th>
                </tr>
              </thead>
              <tbody>
                {oauthApps.map((oauthApp) => {
                  const action = getOAuthAuthorizationAction(oauthApp.flow_status, oauthApp.runtime_status);
                  const credentialVersion = oauthApp.active_credential_version ?? oauthApp.pending_credential_version;
                  return (
                    <tr key={oauthApp.id}>
                      <td>{oauthApp.id}</td>
                      <td className="oauth-app-info">
                        <div>{oauthApp.account_id} / {oauthApp.client_id}</div>
                        <div className="token-meta">{oauthApp.redirect_uri}</div>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => void handleGenerate(oauthApp)}
                          disabled={action.disabled || generatingId === oauthApp.id}
                        >
                          {generatingId === oauthApp.id ? "Generating..." : action.label}
                        </button>
                      </td>
                      <td><StatusBadge value={oauthApp.flow_status} /></td>
                      <td><StatusBadge value={oauthApp.runtime_status} /></td>
                      <td>
                        <div>{credentialVersion === null ? "-" : `v${credentialVersion}`}</div>
                        <div className="token-meta">{shortenCredentialFingerprint(oauthApp.credential_fingerprint)}</div>
                      </td>
                      <td>
                        <div>{oauthApp.failure_class ?? "-"}</div>
                        {oauthApp.failure_count ? <div className="token-meta">Count: {oauthApp.failure_count}</div> : null}
                      </td>
                      <td>{formatDateTime(oauthApp.last_verified_at)}</td>
                      <td>{oauthApp.next_action ?? "-"}</td>
                    </tr>
                  );
                })}
                {oauthApps.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="empty-cell">
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
