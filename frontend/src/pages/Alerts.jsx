import React from 'react'

export default function Alerts({ closed, skips }){
  return (
    <div className="container">
      <h1 className="text-3xl font-semibold mb-4">Alerts</h1>
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-gray-800 p-4 rounded-md">
          <h2 className="font-medium mb-2">Recent exits</h2>
          <ul className="text-sm text-gray-300 space-y-2">
            {(closed||[]).map((c,idx) => (
              <li key={idx}>{c.mint} — {c.close_reason || 'exit'}</li>
            ))}
            {(!closed || closed.length===0) && <li className="text-gray-500">No exits</li>}
          </ul>
        </div>
        <div className="bg-gray-800 p-4 rounded-md">
          <h2 className="font-medium mb-1">Skipped candidates</h2>
          <p className="text-xs text-gray-500 mb-3">
            These tokens were not bought because at least one safety or strategy rule rejected them.
          </p>
          <ul className="text-sm text-gray-300 space-y-2">
            {(skips||[]).map((s,idx) => (
              <li key={idx} className="border-t border-gray-700 pt-2">
                <div className="font-mono text-xs text-gray-400">{s.mint}</div>
                <div>{s.reason}</div>
                <div className="text-xs text-gray-500">{s.source} · {new Date(s.ts * 1000).toLocaleString()}</div>
              </li>
            ))}
            {(!skips || skips.length===0) && <li className="text-gray-500">No skips</li>}
          </ul>
        </div>
      </div>
    </div>
  )
}
