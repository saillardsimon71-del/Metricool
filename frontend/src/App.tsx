import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import Accounts from './pages/Accounts'
import Analytics from './pages/Analytics'
import Automations from './pages/Automations'
import Calendar from './pages/Calendar'
import Composer from './pages/Composer'
import Dashboard from './pages/Dashboard'
import Diagnostics from './pages/Diagnostics'
import Library from './pages/Library'
import Posts from './pages/Posts'
import Settings from './pages/Settings'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/calendar" element={<Calendar />} />
        <Route path="/posts" element={<Posts />} />
        <Route path="/posts/new" element={<Composer />} />
        <Route path="/posts/:postId" element={<Composer />} />
        <Route path="/library" element={<Library />} />
        <Route path="/accounts" element={<Accounts />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/automations" element={<Automations />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/diagnostics" element={<Diagnostics />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  )
}
