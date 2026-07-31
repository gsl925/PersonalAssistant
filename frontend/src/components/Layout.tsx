import { NavLink, Outlet } from "react-router-dom";
import SearchBox from "./SearchBox";

const LINKS = [
  { to: "/", label: "知識庫" },
  { to: "/timeline", label: "Timeline" },
  { to: "/mindmap", label: "Mindmap" },
  { to: "/actions", label: "會議代辦" },
  { to: "/todos", label: "快速代辦" },
  { to: "/chat", label: "問答記錄" },
  { to: "/agents", label: "Agents" },
  { to: "/project-sync", label: "跨 Repo 同步" },
  { to: "/settings", label: "設定" },
];

export default function Layout() {
  return (
    <div className="app-shell">
      <nav className="sidebar">
        <h1>個人知識助理</h1>
        {LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}
            end={link.to === "/"}
          >
            {link.label}
          </NavLink>
        ))}
      </nav>
      <div className="main-area">
        <div className="topbar">
          <SearchBox />
        </div>
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
