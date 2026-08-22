import React, { useState, useEffect } from 'react'
import { useWallet } from '../hooks/useWallet'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function Controls(){
  const { wallet } = useWallet()
  const [loading, setLoading] = useState(null)
  const [message, setMessage] = useState(null)
  const [autoTrading, setAutoTrading] = useState(false)
  const [tradesExecuted, setTradesExecuted] = useState(0)

  // Poll auto-trading status
  useEffect(() => {
    let interval
    const pollStatus = async () => {
      try {
        const res = await fetch(`${API}/api/autotrading/status`)
        if (res.ok) {
          const json = await res.json()
          setAutoTrading(json.active)
          setTradesExecuted(json.trades_executed)
        }
      } catch (err) {
        console.error('Status poll failed:', err)
      }
    }
    
    if (autoTrading) {
      pollStatus()
      interval = setInterval(pollStatus, 2000)
    }
    
    return () => clearInterval(interval)
  }, [autoTrading])

  const handleAutoTrade = async (action) => {
    setLoading(action)
    try {
      const endpoint = action === 'start' ? '/api/autotrading/start' : '/api/autotrading/stop'
      const res = await fetch(`${API}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wallet }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.error || 'Failed')
      setAutoTrading(action === 'start')
      const candidate = json.candidate
      setMessage(action === 'start'
        ? candidate
          ? `Paper position opened for ${candidate.name} (${candidate.symbol})`
          : 'Auto-trading started, but no eligible live token was found'
        : 'Auto-trading stopped')
      setTimeout(() => setMessage(null), 3000)
    } catch (err) {
      setMessage(`Error: ${err.message}`)
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="bg-gray-800 p-4 rounded-md mb-6 border border-gray-700">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-medium">Trading Controls</h2>
        {autoTrading && (
          <div className="flex items-center gap-2 text-green-400">
            <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></div>
            <span className="text-sm">Auto-Trading Active ({tradesExecuted} trades)</span>
          </div>
        )}
      </div>

      <div className="mb-4">
        <div className="flex gap-3">
          {!autoTrading ? (
            <button
              onClick={() => handleAutoTrade('start')}
              disabled={loading}
              className="px-6 py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white rounded-md font-medium transition text-lg">
              {loading === 'start' ? 'Starting...' : '▶ START AUTO-TRADE'}
            </button>
          ) : (
            <button
              onClick={() => handleAutoTrade('stop')}
              disabled={loading}
              className="px-6 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 text-white rounded-md font-medium transition text-lg">
              {loading === 'stop' ? 'Stopping...' : '⏹ STOP AUTO-TRADE'}
            </button>
          )}
        </div>
      </div>

      {message && (
        <div className="mt-3 p-2 bg-gray-700 text-gray-200 rounded text-sm">
          {message}
        </div>
      )}
    </div>
  )
}

