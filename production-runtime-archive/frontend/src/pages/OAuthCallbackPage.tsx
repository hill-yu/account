import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, type ApiError } from "../lib/api";
import { getErrorMessage } from "../lib/errorMessages";
import {
  buildOAuthCallbackFingerprint,
  describeOAuthCallbackResult,
  shouldSkipOAuthCallback,
} from "../lib/oauth";
import type { OAuthCallbackResponse } from "../types/api";

type CallbackState =
  | { phase: "loading" }
  | { phase: "success"; result: OAuthCallbackResponse }
  | { phase: "error"; message: string };

export function OAuthCallbackPage() {
  const [params] = useSearchParams();
  const [state, setState] = useState<CallbackState>({ phase: "loading" });

  useEffect(() => {
    const oauthState = params.get("state");
    const code = params.get("code");
    const error = params.get("error");

    if (error) {
      setState({ phase: "error", message: `Google 授权已取消或失败：${error}` });
      return;
    }

    if (!oauthState || !code) {
      setState({ phase: "error", message: "授权回调缺少必要参数，请回到控制台重新生成授权链接。" });
      return;
    }

    const fingerprint = buildOAuthCallbackFingerprint(oauthState, code);
    if (shouldSkipOAuthCallback(window.sessionStorage, fingerprint)) {
      return;
    }

    void api
      .completeOAuthCallback(oauthState, code)
      .then((result) => setState({ phase: "success", result }))
      .catch((requestError) => {
        setState({ phase: "error", message: getErrorMessage(requestError as ApiError) });
      });
  }, [params]);

  return (
    <div className="callback-page">
      <div className="callback-card">
        <p className="page-kicker">OAuth Callback</p>
        <h2>Google 授权回流</h2>
        {state.phase === "loading" ? <p>正在和控制面确认授权结果，请稍候...</p> : null}
        {state.phase === "success" ? (
          <>
            <p>{describeOAuthCallbackResult(state.result)}</p>
            <ul className="callback-list">
              <li>OAuth App ID：{state.result.oauth_app_id}</li>
              <li>Account ID：{state.result.account_id}</li>
              <li>授权状态：{state.result.authorization_status}</li>
            </ul>
          </>
        ) : null}
        {state.phase === "error" ? (
          <>
            <p>{state.message}</p>
            <p className="token-meta">你可以回到控制台重新生成授权链接，或检查 redirect URI 是否与 Google OAuth 配置一致。</p>
          </>
        ) : null}
        <div className="token-actions">
          <Link to="/" className="primary-button">
            返回 Operations
          </Link>
          <Link to="/reports" className="secondary-button link-button">
            去 Reports
          </Link>
        </div>
      </div>
    </div>
  );
}
