import React from 'react'
import { createRoot } from 'react-dom/client'
import CareerInsights from './components/career/CareerInsights'
import './styles/career-components.css'

createRoot(document.getElementById('root')).render(<main style={{ maxWidth: 1160, margin: '0 auto', padding: '24px 16px', fontFamily: 'sans-serif' }}><CareerInsights /></main>)
