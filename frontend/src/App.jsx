import React, { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import OverviewTab from './tabs/OverviewTab.jsx'
import SignalsTab from './tabs/SignalsTab.jsx'
import StockTab from './tabs/StockTab.jsx'

// Add a tab by adding a row here and a component above. Nothing else to wire.
const TABS = [
  { id: 'overview', label: 'Overview', render: (p) => <OverviewTab {...p} /> },
  { id: 'signals', label: 'Signals', render: (p) => <SignalsTab {...p} /> },
  { id: 'stock', label: 'Stock', render: (p) => <StockTab {...p} /> },
]

export default function App() {
  const [active, setActive] = useState('signals')
  const [symbol, setSymbol] = useState(null)
  const [reloadKey] = useState(0)

  // Clicking a ticker anywhere jumps to the Stock tab with it loaded.
  const onPickSymbol = useCallback((sym) => {
    setSymbol(sym)
    setActive('stock')
  }, [])

  const current = TABS.find((t) => t.id === active) ?? TABS[0]

  return (
    <div className="shell">
      <header className="masthead">
        <div className="masthead-inner">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true" />
            NSE Scanner
          </div>
          <DataStatus key={reloadKey} />
        </div>
        <nav className="tabstrip" role="tablist" aria-label="Sections">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={t.id === active}
              onClick={() => setActive(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="page" role="tabpanel">
        {current.render({ symbol, onPickSymbol })}
      </main>
    </div>
  )
}

/* Where the prices come from and how current they are, with a button to pull
   the latest. Lives in the masthead because it applies to every tab. */
function DataStatus() {
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)

  const load = useCallback(() => {
    api.status().then(setStatus).catch(() => setStatus(null))
  }, [])

  useEffect(() => { load() }, [load])

  async function refresh() {
    setBusy(true)
    setNote(null)
    try {
      const out = await api.refresh()
      setNote(out.message)
      load()
    } catch (e) {
      setNote(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (!status) return <span className="masthead-note">Connecting to the backend…</span>

  const f = status.freshness || {}
  const tone = f.state === 'current' ? 'ok' : f.state === 'stale' ? 'warn' : ''

  return (
    <span className="masthead-note">
      <span>{status.source}</span>
      {f.message && <span className={`chip-state ${tone}`}>{note || f.message}</span>}
      {status.can_refresh && (
        <button className="btn btn-quiet btn-small" onClick={refresh} disabled={busy}>
          {busy ? <><span className="spinner" /> Refreshing</> : 'Refresh prices'}
        </button>
      )}
    </span>
  )
}
