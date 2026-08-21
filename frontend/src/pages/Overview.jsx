import React from 'react'
import Controls from '../components/Controls'
import { useWallet } from '../hooks/useWallet'

export default function Overview({ data }){
  const { wallet, balance, balanceSource } = useWallet()
  const counts = data?.counts || { open_count: 0, closed_count: 0, skip_count: 0 }
  
  return (
    <div className="container">
      <h1 className="text-3xl font-semibold mb-4">Dashboard</h1>
      <Controls />
      
      {wallet && (
        <div className="mb-6 bg-cyan-900 bg-opacity-30 border border-cyan-600 p-4 rounded-md">
          <h2 className="text-lg font-medium text-cyan-300 mb-3">Wallet Portfolio</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-sm text-gray-400">Wallet Address</div>
              <div className="text-md font-mono text-gray-100">{wallet}</div>
            </div>
            <div>
              <div className="text-sm text-gray-400">SOL Balance</div>
              <div className="text-2xl font-bold text-cyan-300">{balance.toFixed(4)} SOL</div>
              <div className={`text-xs mt-1 ${balanceSource === 'live' ? 'text-green-400' : 'text-yellow-400'}`}>
                {balanceSource === 'live' ? 'Live Solana RPC balance' : 'RPC unavailable; fallback balance shown'}
              </div>
            </div>
          </div>
        </div>
      )}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-gray-800 p-4 rounded-md"> 
          <h3 className="text-sm text-gray-400">Open positions</h3>
          <div className="text-2xl font-bold mt-2">{counts.open_count}</div>
        </div>
        <div className="bg-gray-800 p-4 rounded-md"> 
          <h3 className="text-sm text-gray-400">Closed positions</h3>
          <div className="text-2xl font-bold mt-2">{counts.closed_count}</div>
        </div>
        <div className="bg-gray-800 p-4 rounded-md"> 
          <h3 className="text-sm text-gray-400">Skipped candidates (all time)</h3>
          <div className="text-2xl font-bold mt-2">{counts.skip_count}</div>
          <div className="text-xs text-gray-500 mt-1">Rejected by a safety rule</div>
        </div>
      </div>

      <section className="mt-6 bg-gray-800 rounded-md p-4">
        <h2 className="text-lg font-medium mb-2">Recent Activity</h2>
        <ul className="space-y-2 text-sm text-gray-300">
          {(data?.closed || []).slice(0,3).map((c,idx) => (
            <li key={idx}>{c.mint} closed — {c.close_reason || 'exit'}</li>
          ))}
          {(!data?.closed || data.closed.length===0) && <li className="text-gray-500">No recent exits</li>}
        </ul>
      </section>
    </div>
  )
}
