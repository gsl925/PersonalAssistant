import { NavLink, Outlet } from "react-router-dom";
import SearchBox from "./SearchBox";

const LINKS = [
  { to: "/", label: "Project" },
  { to: "/timeline", label: "Timeline" },
  { to: "/mindmap", label: "Mindmap" },
  { to: "/actions", label: "會議代辦" },
  { to: "/todos", label: "快速代辦" },
  { to: "/agents", label: "Agents" },
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
