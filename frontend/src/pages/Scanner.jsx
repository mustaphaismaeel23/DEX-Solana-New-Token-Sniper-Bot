import React, { useState, useEffect } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function Scanner(){
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedToken, setSelectedToken] = useState(null)
  const [details, setDetails] = useState(null)
  const [source, setSource] = useState('cached')
  const [detailsLoading, setDetailsLoading] = useState(false)

  useEffect(() => {
    fetchTokens()
  }, [])

  const fetchTokens = async () => {
    try {
      const res = await fetch(`${API}/api/scanner/tokens`)
      const json = await res.json()
      setTokens(json.tokens || [])
      setSource(json.source || 'cached')
    } catch (err) {
      console.error('Failed to fetch tokens:', err)
    } finally {
      setLoading(false)
    }
  }

  const fetchTokenDetails = async (mint) => {
    setDetailsLoading(true)
    try {
      const res = await fetch(`${API}/api/scanner/token/${mint}`)
      const json = await res.json()
      if (!res.ok) throw new Error(json.error || 'Could not load token details')
      setDetails(json)
      setSelectedToken(mint)
    } catch (err) {
      console.error('Failed to fetch token details:', err)
    } finally {
      setDetailsLoading(false)
    }
  }

  const getRiskColor = (score) => {
    if (score < 30) return 'text-green-400 bg-green-900'
    if (score < 70) return 'text-yellow-400 bg-yellow-900'
    return 'text-red-400 bg-red-900'
  }

  const getRiskLabel = (score) => {
    if (score < 30) return 'LOW RISK'
    if (score < 70) return 'MEDIUM RISK'
    return 'HIGH RISK'
  }

  return (
    <div className="container">
      <h1 className="text-3xl font-semibold mb-4">Token Scanner</h1>
      <div className="flex items-center justify-between mb-6 gap-3">
        <p className="text-gray-400">Live Solana pairs, market data, and rug-risk signals</p>
        <button onClick={fetchTokens} className="px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm">
          Refresh {source === 'dexscreener' ? '(live)' : '(cached)'}
        </button>
      </div>

      {loading ? (
        <div className="text-gray-400">Loading tokens...</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Token List */}
          <div className="lg:col-span-2">
            <div className="bg-gray-800 rounded-md overflow-hidden">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-900 text-gray-400">
                  <tr>
                    <th className="p-3 text-left">Token</th>
                    <th className="p-3 text-left">Market Cap</th>
                    <th className="p-3 text-left">Liquidity</th>
                    <th className="p-3 text-left">Price / 24h</th>
                    <th className="p-3 text-center">Risk</th>
                    <th className="p-3 text-center">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {tokens.map(t => (
                    <tr key={t.id} className="border-t border-gray-700 hover:bg-gray-750 cursor-pointer" onClick={() => fetchTokenDetails(t.mint)}>
                      <td className="p-3">
                        <div className="font-medium">{t.symbol}</div>
                        <div className="text-xs text-gray-500">{t.name}</div>
                      </td>
                      <td className="p-3">${(t.market_cap / 1000).toFixed(0)}K</td>
                      <td className="p-3">${(t.liquidity / 1000).toFixed(0)}K</td>
                      <td className={`p-3 ${t.price_change_24h >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        <div>${t.price_usd > 0 ? t.price_usd.toPrecision(5) : 'n/a'}</div>
                        <div className="text-xs">{t.price_change_24h == null ? 'n/a' : `${t.price_change_24h.toFixed(1)}%`}</div>
                      </td>
                      <td className={`p-3 text-center rounded font-bold ${getRiskColor(t.risk_score)}`}>
                        {getRiskLabel(t.risk_score)}
                      </td>
                      <td className="p-3 text-center">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            fetchTokenDetails(t.mint)
                          }}
                          className="px-2 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs">
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Token Details */}
          {detailsLoading && <div className="bg-gray-800 rounded-md p-4 border border-gray-700">Loading live token data...</div>}
          {details && !detailsLoading && (
            <div className="bg-gray-800 rounded-md p-4 border border-gray-700 h-fit sticky top-4">
              <h3 className="text-lg font-bold mb-4 text-cyan-300">{details.token.symbol} Details</h3>
              
              <div className="space-y-3 text-sm mb-4">
                <div>
                  <div className="text-gray-400">Mint</div>
                  <div className="text-xs font-mono text-gray-300">{details.token.mint}</div>
                </div>
                <div>
                  <div className="text-gray-400">Market Cap</div>
                  <div className="font-medium">${(details.token.market_cap / 1000000).toFixed(2)}M</div>
                </div>
                <div>
                  <div className="text-gray-400">Liquidity</div>
                  <div className="font-medium">${(details.token.liquidity / 1000).toFixed(0)}K</div>
                </div>
                <div>
                  <div className="text-gray-400">Holders</div>
                  <div className="font-medium">
                    {details.token.holders == null
                      ? 'Not indexed'
                      : `${details.token.holders.toLocaleString()}${details.token.holders_estimated ? '+' : ''}`}
                  </div>
                </div>
                <div>
                  <div className="text-gray-400">Top 10 Holdings</div>
                  <div className="font-medium">{details.token.top10_holdings == null ? 'Unavailable from DexScreener' : `${details.token.top10_holdings.toFixed(1)}%`}</div>
                </div>
              </div>

              <div className="border-t border-gray-700 pt-4 mb-4">
                <h4 className="font-medium mb-3 text-gray-300">Risk Factors</h4>
                <div className="space-y-2 text-xs">
                  {Object.entries(details.risk_factors).map(([key, value]) => (
                    <div key={key} className={`flex items-center gap-2 ${value ? 'text-red-400' : 'text-green-400'}`}>
                      <span className={`text-lg ${value ? '⚠️' : '✓'}`}></span>
                      <span>{key.replace(/_/g, ' ').toUpperCase()}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="border-t border-gray-700 pt-4">
                <div className="mb-3">
                  <div className="text-gray-400 text-xs">Rugpull Probability</div>
                  <div className={`text-2xl font-bold ${details.token.rugpull_probability > 0.5 ? 'text-red-400' : 'text-green-400'}`}>
                    {(details.token.rugpull_probability * 100).toFixed(0)}%
                  </div>
                </div>
                {details.token.rugpull_probability > 0.5 && (
                  <button
                    onClick={() => fetch(`${API}/api/scanner/alert/${details.token.mint}`, { method: 'POST' })}
                    className="w-full px-3 py-2 bg-red-600 hover:bg-red-700 text-white rounded font-medium text-sm">
                    🚨 TRIGGER RUGPULL ALERT
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
