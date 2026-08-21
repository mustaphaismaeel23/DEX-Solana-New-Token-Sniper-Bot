import React, { useState, useEffect } from 'react'
import { VersionedTransaction } from '@solana/web3.js'
import { useWallet } from '../hooks/useWallet'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const SOL_MINT = 'So11111111111111111111111111111111111111112'

export default function Controls(){
  const { wallet } = useWallet()
  const [loading, setLoading] = useState(null)
  const [message, setMessage] = useState(null)
  const [autoTrading, setAutoTrading] = useState(false)
  const [tradesExecuted, setTradesExecuted] = useState(0)
  const [mint, setMint] = useState('')
  const [amount, setAmount] = useState('0.02')
  const [minimumBuySol, setMinimumBuySol] = useState(null)

  useEffect(() => {
    fetch(`${API}/api/trading/requirements`)
      .then(response => response.json())
      .then(json => {
        if (json.minimum_trade_sol) {
          setMinimumBuySol(json.minimum_trade_sol)
          setAmount(json.minimum_trade_sol.toFixed(6))
        }
      })
      .catch(error => console.error('Could not load trading requirements:', error))
  }, [])

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

  const handleAction = async (action) => {
    setLoading(action)
    try {
      if ((action === 'buy' || action === 'sell') && mint.trim() && wallet) {
        if (!window.solana?.signAndSendTransaction) throw new Error('Connected wallet does not support transaction signing')
        const isBuy = action === 'buy'
        const rawAmount = isBuy
          ? Math.round(Number(amount) * 1e9)
          : Math.round(Number(amount))
        if (!Number.isSafeInteger(rawAmount) || rawAmount <= 0) throw new Error('Enter a valid positive amount')
        if (isBuy && minimumBuySol != null && Number(amount) < minimumBuySol) {
          throw new Error(`Minimum BUY amount is ${minimumBuySol.toFixed(6)} SOL`)
        }

        const quoteRes = await fetch(`${API}/api/trade/quote`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            input_mint: isBuy ? SOL_MINT : mint.trim(),
            output_mint: isBuy ? mint.trim() : SOL_MINT,
            amount: rawAmount,
          }),
        })
        const quote = await quoteRes.json()
        if (!quoteRes.ok) throw new Error(quote.error || 'Quote failed')

        const swapRes = await fetch(`${API}/api/trade/swap-transaction`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ quote, wallet }),
        })
        const swap = await swapRes.json()
        if (!swapRes.ok) throw new Error(swap.error || 'Could not prepare swap')

        const bytes = Uint8Array.from(atob(swap.swapTransaction), char => char.charCodeAt(0))
        const transaction = VersionedTransaction.deserialize(bytes)
        const signed = await window.solana.signAndSendTransaction(transaction)
        const recorded = await fetch(`${API}/api/${action}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mint: mint.trim(), wallet, amount: Number(amount), signature: signed.signature, quote }),
        })
        if (!recorded.ok) throw new Error('Transaction signed but position confirmation failed')
        const confirmation = await recorded.json()
        setMessage(`${action.toUpperCase()} confirmed: ${signed.signature} (${confirmation.position_opened ? 'position opened' : confirmation.position_closed ? 'position closed' : 'recorded'})`)
      } else {
        const res = await fetch(`${API}/api/${action}`, { method: 'POST' })
        if (!res.ok) throw new Error('Failed')
        const json = await res.json()
        setMessage(`${action.toUpperCase()} signal recorded: ${json.timestamp}`)
      }
      setTimeout(() => setMessage(null), 3000)
    } catch (err) {
      setMessage(`Error: ${err.message}`)
    } finally {
      setLoading(null)
    }
  }

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

      <div className="border-t border-gray-700 pt-4">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Manual Controls</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
          <input
            value={mint}
            onChange={event => setMint(event.target.value)}
            placeholder="Token mint for wallet trade"
            className="md:col-span-2 bg-gray-900 border border-gray-600 rounded-md px-3 py-2 text-sm font-mono"
          />
          <input
            value={amount}
            onChange={event => setAmount(event.target.value)}
            type="number"
            min="0"
            step="any"
            placeholder="Buy SOL / sell raw units"
            className="bg-gray-900 border border-gray-600 rounded-md px-3 py-2 text-sm"
          />
        </div>
        <div className="text-xs text-gray-500 mb-3">
          Minimum BUY: {minimumBuySol == null ? 'loading...' : `${minimumBuySol.toFixed(6)} SOL`}. Connect a wallet and enter a mint for a real Jupiter swap. SELL uses raw token units.
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => handleAction('buy')}
            disabled={loading}
            className="px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white rounded-md font-medium transition">
            {loading === 'buy' ? 'Loading...' : 'BUY'}
          </button>
          <button
            onClick={() => handleAction('sell')}
            disabled={loading}
            className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 text-white rounded-md font-medium transition">
            {loading === 'sell' ? 'Loading...' : 'SELL'}
          </button>
          <button
            onClick={() => handleAction('stop')}
            disabled={loading}
            className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 disabled:bg-gray-600 text-white rounded-md font-medium transition">
            {loading === 'stop' ? 'Loading...' : 'STOP'}
          </button>
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

