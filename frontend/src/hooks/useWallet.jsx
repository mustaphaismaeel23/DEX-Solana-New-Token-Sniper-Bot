import React, { useState, useCallback, useEffect } from 'react'

const WalletContext = React.createContext()
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export function WalletProvider({ children }){
  const [wallet, setWallet] = useState(null)
  const [balance, setBalance] = useState(0)
  const [balanceSource, setBalanceSource] = useState('unknown')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setWallet(null)
    setBalance(0)
    setBalanceSource('unknown')
    if (window.solana?.isConnected) {
      window.solana.disconnect().catch(() => {})
    }
  }, [])

  const connectWallet = useCallback(async () => {
    setLoading(true)
    setError(null)
    try{
      if (!window.solana?.connect) throw new Error('No compatible Solana wallet extension found')
      const response = await window.solana.connect()
      if(response){
        setWallet(response.publicKey.toString())
        const res = await fetch(`${API}/api/wallet/balance?address=${encodeURIComponent(response.publicKey.toString())}`)
        const json = await res.json()
        if (!res.ok) throw new Error(json.error || 'Could not fetch wallet balance')
        setBalance(Number(json.balance) || 0)
        setBalanceSource(json.source || 'unknown')
      }
    }catch(err){
      setError(err.message)
      console.error('Wallet connection failed:', err)
    }finally{
      setLoading(false)
    }
  }, [])

  const disconnectWallet = useCallback(() => {
    setWallet(null)
    setBalance(0)
    setBalanceSource('unknown')
    setError(null)
    window.solana?.disconnect()
  }, [])

  return (
    <WalletContext.Provider value={{ wallet, balance, balanceSource, error, loading, connectWallet, disconnectWallet }}>
      {children}
    </WalletContext.Provider>
  )
}

export function useWallet(){
  return React.useContext(WalletContext)
}
