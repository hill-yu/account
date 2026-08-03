import { FormEvent, useState } from "react";

import { api, type ApiError } from "../lib/api";
import { getErrorMessage } from "../lib/errorMessages";

interface LoginPageProps {
  onAuthenticated: () => void;
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.loginOperator(password);
      setPassword("");
      onAuthenticated();
    } catch (requestError) {
      setError(getErrorMessage(requestError as ApiError));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <p className="page-kicker">ADX Collector</p>
        <h1>管理员登录</h1>
        <p>请输入中台管理员密码以继续。</p>
        <label className="field">
          <span className="field-label">管理员密码</span>
          <input
            className="field-control"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            autoFocus
          />
        </label>
        {error ? <p className="login-error" role="alert">{error}</p> : null}
        <button className="primary-button" type="submit" disabled={submitting}>
          {submitting ? "正在登录…" : "登录"}
        </button>
      </form>
    </main>
  );
}
