import { NavLink, Outlet } from "react-router-dom";

import { api } from "../../lib/api";

export function AppShell() {
  async function handleLogout() {
    await api.logoutOperator();
    window.location.assign("/");
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="brand-block">
          <p className="brand-kicker">ADX Collector</p>
          <h1>Control Plane</h1>
          <p>面向单账号执行节点的最小控制台，统一管理账号、节点、代理和中台聚合报表。</p>
        </div>
        <nav className="app-nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Operations
          </NavLink>
          <NavLink to="/reports" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Reports
          </NavLink>
        </nav>
        <button className="secondary-button" type="button" onClick={() => void handleLogout()}>
          退出登录
        </button>
      </aside>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
