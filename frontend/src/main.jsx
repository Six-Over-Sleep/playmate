import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles/auth.css'
import './styles/navigation.css'
import './styles/board-components.css'
import './styles/admin.css'
import './styles/mypage-components.css'
import './styles/career-components.css'
import './styles/board-foundation.css'
import './styles/meetup-foundation.css'
import './styles/base.css'
import './styles/home.css'
import './styles/board.css'
import './styles/meetup.css'
import './styles/navigation-board.css'
import './styles/career.css'
import './styles/career-insights.css'
import './styles/mypage.css'
import './styles/board-responsive.css'
import './styles/home-insights.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

