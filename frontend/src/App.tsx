import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ProjectView from "./components/ProjectView";
import TimelineView from "./components/TimelineView";
import MindmapView from "./components/MindmapView";
import ActionItemsPanel from "./components/ActionItemsPanel";
import TodosView from "./components/TodosView";
import SettingsView from "./components/SettingsView";
import AgentsView from "./components/AgentsView";
import ProjectSyncView from "./components/ProjectSyncView";
import ChatView from "./components/ChatView";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ProjectView />} />
        <Route path="timeline" element={<TimelineView />} />
        <Route path="mindmap" element={<MindmapView />} />
        <Route path="actions" element={<ActionItemsPanel />} />
        <Route path="todos" element={<TodosView />} />
        <Route path="chat" element={<ChatView />} />
        <Route path="agents" element={<AgentsView />} />
        <Route path="project-sync" element={<ProjectSyncView />} />
        <Route path="settings" element={<SettingsView />} />
      </Route>
    </Routes>
  );
}
