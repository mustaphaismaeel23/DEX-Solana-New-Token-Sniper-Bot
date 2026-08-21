import React, { useState, useEffect } from 'react'
import { WalletProvider } from './hooks/useWallet'
import Navbar from './components/Navbar'
import Overview from './pages/Overview'
import Positions from './pages/Positions'
import Alerts from './pages/Alerts'
import Scanner from './pages/Scanner'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function AppContent(){
  const [route, setRoute] = useState('overview')
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let mounted = true
    async function fetchData(){
      try{
        const res = await fetch(`${API}/api/dashboard`, { 
          method: 'GET',
          headers: { 'Content-Type': 'application/json' }
        })
        if(!res.ok) throw new Error(`HTTP ${res.status}`)
        const json = await res.json()
        if(mounted) {
          setData(json)
          setError(null)
        }
      }catch(err){
        if(mounted) {
          setError(`Backend unreachable (${API}). Make sure backend is running: python backend_api.py`)
          console.error('Fetch error:', err)
        }
      }
    }
    fetchData()
    const id = setInterval(fetchData, 5000)
    return () => { mounted = false; clearInterval(id) }
  }, [])

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100">
      <Navbar onNavigate={setRoute} active={route} />
      <main className="p-6">
        {error && (
          <div className="bg-red-900 text-red-200 p-4 rounded mb-4 border border-red-700">
            <div className="font-bold mb-2">⚠️ Connection Error</div>
            <div className="text-sm">{error}</div>
          </div>
        )}
        {route === 'overview' && <Overview data={data} />}
        {route === 'positions' && <Positions positions={data?.positions || []} />}
        {route === 'alerts' && <Alerts closed={data?.closed || []} skips={data?.skips || []} />}
        {route === 'scanner' && <Scanner />}
      </main>
    </div>
  )
}

export default function App(){
  return (
    <WalletProvider>
      <AppContent />
    </WalletProvider>
  )
}

