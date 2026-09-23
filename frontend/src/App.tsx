import { NavLink, Route, Routes } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import { AccuracyPage } from './pages/Accuracy'
import { AuthPage } from './pages/Auth'
import { DeadlinePage } from './pages/Deadline'
import { HomePage } from './pages/Home'
import { HomeCheckPage } from './pages/HomeCheck'
import { DisclaimerPage, ImpressumPage, PrivacyPage } from './pages/Legal'
import { MyTripsPage } from './pages/MyTrips'

function App() {
  const { loggedIn } = useAuth()
  return (
    <div className="page-shell">
      <header className="topbar">
        <NavLink to="/" className="brand">Heimkommen</NavLink>
        <nav aria-label="Main">
          <NavLink to="/deadline">Deadline</NavLink>
          <NavLink to="/accuracy">Accuracy</NavLink>
          {loggedIn ? <NavLink to="/trips">My trips</NavLink> : <NavLink to="/login">Log in</NavLink>}
        </nav>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/check" element={<HomeCheckPage />} />
          <Route path="/deadline" element={<DeadlinePage />} />
          <Route path="/accuracy" element={<AccuracyPage />} />
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route path="/trips" element={<MyTripsPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="/impressum" element={<ImpressumPage />} />
          <Route path="/about" element={<DisclaimerPage />} />
          <Route path="*" element={<p className="empty-message">Page not found.</p>} />
        </Routes>
      </main>

      <footer className="footer">
        <p>
          Timetable © <a href="https://www.nvbw.de/open-data">NVBW</a> · Delay history{' '}
          <a href="https://github.com/piebro/deutsche-bahn-data">piebro/deutsche-bahn-data</a> (CC BY 4.0, data by Deutsche Bahn)
          · Live data: DB Timetables API · Map © OpenStreetMap contributors
        </p>
        <p>
          Not an official Deutsche Bahn service. Predictions are estimates. ·{' '}
          <NavLink to="/about">About the predictions</NavLink> · <NavLink to="/privacy">Privacy</NavLink> ·{' '}
          <NavLink to="/impressum">Impressum</NavLink>
        </p>
      </footer>
    </div>
  )
}

export default App
