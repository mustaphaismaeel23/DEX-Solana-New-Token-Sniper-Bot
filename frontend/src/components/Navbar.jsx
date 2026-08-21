import React from 'react'
import { useWallet } from '../hooks/useWallet'

export default function Navbar({ onNavigate, active }){
  const { wallet, balance, error, connectWallet, disconnectWallet } = useWallet()
  const items = [
    { key: 'overview', label: 'Overview' },
    { key: 'positions', label: 'Positions' },
    { key: 'scanner', label: 'Scanner' },
    { key: 'alerts', label: 'Alerts' }
  ]
  
  return (
    <header className="bg-gray-800 border-b border-gray-700">
      <div className="container flex items-center justify-between py-4 px-4">
        <div className="flex items-center gap-3">
          <div className="text-2xl font-bold text-cyan-400">DEX TRADE BOT</div>
          <div className="text-sm text-gray-400">Automated Solana Trading</div>
        </div>
        <nav className="flex items-center gap-3">
          {items.map(i => (
            <button
              key={i.key}
              onClick={() => onNavigate(i.key)}
              className={`px-3 py-2 rounded-md text-sm font-medium ${active===i.key ? 'bg-gray-700' : 'text-gray-300 hover:bg-gray-700'}`}>
              {i.label}
            </button>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          {wallet ? (
            <div className="flex items-center gap-2">
              <div className="text-right">
                <div className="text-sm font-medium">{wallet.slice(0, 8)}...{wallet.slice(-8)}</div>
                <div className={`text-xs ${error ? 'text-red-400' : 'text-gray-400'}`}>
                  {error ? 'Balance unavailable' : `${balance.toFixed(4)} SOL`}
                </div>
              </div>
              <button
                onClick={disconnectWallet}
                className="px-3 py-2 bg-red-600 hover:bg-red-700 text-white rounded-md text-sm font-medium">
                Disconnect
              </button>
            </div>
          ) : (
            <button
              onClick={connectWallet}
              className="px-4 py-2 bg-cyan-600 hover:bg-cyan-700 text-white rounded-md font-medium">
              Connect Wallet
            </button>
          )}
        </div>
      </div>
    </header>
  )
}

