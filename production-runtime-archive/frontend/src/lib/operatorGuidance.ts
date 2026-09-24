export function buildOAuthRedirectUriHint(): string {
  return "Set redirect_uri to this account's own website callback URL. Do not default to the control plane callback, and do not reuse another account's callback URL.";
}

export function buildInstanceOnboardingNote(): string {
  return "Create a second account first, then create that account's own instance instead of attaching a second node under the first account.";
}

export function buildSecondAccountChecklist(): string[] {
  return [
    "Create the second account.",
    "Create the second account's instance.",
    "Create the second account's OAuth app.",
    "Set redirect_uri to the second account website callback.",
    "Generate the authorization URL, download the callback JSON from the account site, and import it in this control plane.",
  ];
}

export function buildOAuthJsonImportHint(): string {
  return "Upload the callback JSON in the control plane operator flow only. user_system must not host or proxy this onboarding step.";
}

export interface OAuthAuthorizationAction {
  label: string;
  disabled: boolean;
  forceReauthorize: boolean;
  requiresConfirmation: boolean;
}

export function getOAuthAuthorizationAction(
  flowStatus: string,
  runtimeStatus: string,
): OAuthAuthorizationAction {
  if (flowStatus === "validation_pending") {
    return { label: "Validation pending", disabled: true, forceReauthorize: false, requiresConfirmation: false };
  }
  if (flowStatus === "requested") {
    return { label: "Authorization requested", disabled: true, forceReauthorize: false, requiresConfirmation: false };
  }
  if (runtimeStatus === "degraded") {
    return { label: "Health check running", disabled: true, forceReauthorize: false, requiresConfirmation: false };
  }
  if (runtimeStatus === "policy_blocked") {
    return { label: "Resolve policy", disabled: true, forceReauthorize: false, requiresConfirmation: false };
  }
  if (runtimeStatus === "revoked") {
    return { label: "Restore authorization", disabled: false, forceReauthorize: true, requiresConfirmation: false };
  }
  if (runtimeStatus === "healthy") {
    return { label: "Reauthorize", disabled: false, forceReauthorize: true, requiresConfirmation: true };
  }
  return { label: "Generate URL", disabled: false, forceReauthorize: false, requiresConfirmation: false };
}

export function shortenCredentialFingerprint(fingerprint: string | null): string {
  return fingerprint ? fingerprint.slice(0, 12) : "-";
}
