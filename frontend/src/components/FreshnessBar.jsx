import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { prettyDate } from './ui.jsx'

/*
  A one-line verdict on how current the prices are, with a way to fix it.

  Running locally, Refresh downloads whatever sessions are missing straight
  from NSE and finishes in seconds.

  Running on a host that NSE won't answer, Refresh asks GitHub Actions to do
  the collecting instead. That takes a few minutes and ends with a redeploy, so
  the panel says so plainly rather than pretending it was instant.
*/

const TONE = {
  current: 'fresh',
  likely_current: 'fresh',
  stale: 'warn',
  missing: 'warn',
}

export default function FreshnessBar({ onRefreshed }) {
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState(null)
  const [error, setError] = useState(null)

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api.status())
    } catch {
      setStatus(null)
    }
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  async function refresh() {
    setBusy(true); setError(null); setNotice(null)
    try {
      const result = await api.refresh()
      setNotice(result.message)
      await loadStatus()
      if (result.mode === 'local') onRefreshed?.(result)
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!status?.freshness) return null

  const f = status.freshness
  const tone = TONE[f.state] || 'warn'

  return (
    <div className={`freshness freshness-${tone}`}>
      <span className="freshness-dot" aria-hidden="true" />
      <span className="freshness-text">
        {status.latest_session
          ? <>Prices through <b>{prettyDate(status.latest_session)}</b>. {f.message}</>
          : f.message}
      </span>

      {status.mode === 'snapshot' && (
        <span className="freshness-meta">
          snapshot built {prettyDate(status.snapshot_built_at?.slice(0, 10))}
        </span>
      )}

      {status.can_refresh && (
        <button className="btn btn-quiet freshness-btn" onClick={refresh} disabled={busy}>
          {busy ? <><span className="spinner" /> Refreshing</> : 'Refresh data'}
        </button>
      )}

      {(notice || error) && (
        <p className={`freshness-result ${error ? 'is-error' : ''}`}>
          {error || notice}
        </p>
      )}
    </div>
  )
}
