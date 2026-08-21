import React from 'react'

export default function Positions({ positions }){
  return (
    <div className="container">
      <h1 className="text-3xl font-semibold mb-4">Positions</h1>
      <div className="bg-gray-800 rounded-md overflow-hidden">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-900 text-gray-400">
            <tr>
              <th className="p-3 text-left">Symbol</th>
              <th className="p-3 text-left">Size</th>
              <th className="p-3 text-left">Entry</th>
              <th className="p-3 text-left">P&L</th>
            </tr>
          </thead>
          <tbody>
            {(positions||[]).map(p => (
              <tr key={p.id} className="border-t border-gray-700">
                <td className="p-3">{p.mint}</td>
                <td className="p-3">{p.token_amount}</td>
                <td className="p-3">{p.entry_price_sol}</td>
                <td className={`p-3 font-medium ${p.peak_price_sol >= p.entry_price_sol ? 'text-green-400' : 'text-red-400'}`}>{p.peak_price_sol}</td>
              </tr>
            ))}
            {(!positions || positions.length===0) && (
              <tr><td colSpan={4} className="p-4 text-gray-400">No open positions</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
