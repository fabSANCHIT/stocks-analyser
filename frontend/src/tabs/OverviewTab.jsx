import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import FreshnessBar from '../components/FreshnessBar.jsx'
import {
  Panel, Loading, ErrorNote, Change, money, compact, prettyDate,
} from '../components/ui.jsx'

export default function OverviewTab({ onPickSymbol }) {
  const [market, setMarket] = useState(null)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(true)

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const [m, s] = await Promise.all([api.market(), api.status()])
      setMarket(m)
      setStatus(s)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => { load() }, [])

  if (busy && !market) return <Panel><Loading>Reading the latest session</Loading></Panel>
  if (error) return <ErrorNote error={error} onRetry={load} />
  if (!market) return null

  const b = market.index_breadth
  const total = Math.max(1, b.advances + b.declines + b.unchanged)
  const pct = (n) => `${(n / total) * 100}%`

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <FreshnessBar onRefreshed={load} />

      <Panel
        title={`Nifty 100 breadth`}
        note={`Close of ${prettyDate(market.session_date)} vs ${prettyDate(market.previous_date)}`}
      >
        <div className="breadth">
          {b.advances > 0 && (
            <div className="adv" style={{ width: pct(b.advances) }}>{b.advances} up</div>
          )}
          {b.unchanged > 0 && (
            <div className="unc" style={{ width: pct(b.unchanged) }}>{b.unchanged}</div>
          )}
          {b.declines > 0 && (
            <div className="dec" style={{ width: pct(b.declines) }}>{b.declines} down</div>
          )}
        </div>
        <p style={{ color: 'var(--text-faint)', fontSize: 12.5, margin: '12px 0 0' }}>
          Across all of NSE, {market.breadth.advances} of {market.stats.symbols_traded} traded
          stocks closed higher.
        </p>
      </Panel>

      <div className="grid-2">
        <MoverTable title="Top gainers" rows={market.gainers} onPickSymbol={onPickSymbol} />
        <MoverTable title="Top losers" rows={market.losers} onPickSymbol={onPickSymbol} />
      </div>

      <Panel title="Most traded by value" note="Turnover, latest session" bodyless>
        <div className="table-scroll">
          <table className="data">
            <thead>
              <tr>
                <th>Ticker</th><th>Company</th>
                <th className="num">Turnover</th><th className="num">Change</th>
              </tr>
            </thead>
            <tbody>
              {market.most_active.map((r) => (
                <tr key={r.symbol}>
                  <td className="ticker">
                    <button className="linkish ticker" onClick={() => onPickSymbol(r.symbol)}>{r.symbol}</button>
                  </td>
                  <td className="company" title={r.company}>{r.company}</td>
                  <td className="num">₹{compact(r.turnover_cr * 1e7)}</td>
                  <td><Change value={r.change_pct} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {status && <SourcePanel status={status} onRefresh={load} />}
    </div>
  )
}

function MoverTable({ title, rows, onPickSymbol }) {
  return (
    <Panel title={title} bodyless>
      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th>Ticker</th><th>Company</th>
              <th className="num">Close</th><th className="num">Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol}>
                <td className="ticker">
                  <button className="linkish ticker" onClick={() => onPickSymbol(r.symbol)}>{r.symbol}</button>
                </td>
                <td className="company" title={r.company}>{r.company}</td>
                <td className="num">{money(r.close)}</td>
                <td><Change value={r.change_pct} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

/* Where the Kite build showed your broker profile, this shows what data you
   have locally - the useful equivalent when there's no account to log into. */
function SourcePanel({ status, onRefresh }) {
  const [warming, setWarming] = useState(false)
  const c = status.cache
  const u = status.universe

  async function warm() {
    setWarming(true)
    try {
      await api.warmCache(150)
      await onRefresh()
    } finally {
      setWarming(false)
    }
  }

  return (
    <Panel title="Data source" note={status.cost}>
      <dl className="meta-list">
        <dt>Provider</dt><dd>{status.source}</dd>
        <dt>Universe</dt>
        <dd>{u ? `${u.index} · ${u.count} stocks · list refreshed ${prettyDate(u.fetched.slice(0, 10))}` : '—'}</dd>
        <dt>Sessions cached</dt>
        <dd className="num-inline">
          {c.cached_days}
          {c.earliest && (
            <span style={{ fontFamily: 'var(--font-ui)', color: 'var(--text-faint)' }}>
              {' '}({prettyDate(c.earliest)} – {prettyDate(c.latest)}, {c.size_mb} MB)
            </span>
          )}
        </dd>
        <dt>Stored at</dt><dd className="num-inline" style={{ fontSize: 12.5 }}>{c.location}</dd>
      </dl>

      {u?.industries?.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ color: 'var(--text-faint)', fontSize: 12, marginBottom: 8 }}>
            Sectors in the index
          </div>
          <div className="chips">
            {u.industries.map((i) => <span className="chip" key={i}>{i}</span>)}
          </div>
        </div>
      )}

      <button className="btn btn-quiet" style={{ marginTop: 18 }} onClick={warm} disabled={warming}>
        {warming ? <><span className="spinner" /> Downloading</> : 'Download 150 sessions now'}
      </button>
      <p style={{ color: 'var(--text-faint)', fontSize: 12.5, margin: '10px 0 0', maxWidth: '68ch' }}>
        Downloading ahead of time means your scans return instantly. Sessions are kept
        permanently, so this only ever fetches days you don't already have.
      </p>
    </Panel>
  )
}
