import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Panel, Loading, ErrorNote, Empty, Change, money, prettyDate } from '../components/ui.jsx'

export default function StockTab({ symbol }) {
  const [input, setInput] = useState(symbol || '')
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (symbol) { setInput(symbol); load(symbol) }
  }, [symbol])

  async function load(sym) {
    const clean = (sym || '').trim().toUpperCase()
    if (!clean) return
    setBusy(true); setError(null)
    try {
      setData(await api.stock(clean, { days: 200 }))
    } catch (e) {
      setError(e); setData(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <Panel>
        <div className="controls">
          <label className="field">
            <span>Ticker</span>
            <input type="text" value={input} placeholder="RELIANCE" className="ticker-input"
              onChange={(e) => setInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === 'Enter' && load(input)} />
          </label>
          <button className="btn" onClick={() => load(input)} disabled={busy || !input.trim()}>
            {busy ? <><span className="spinner" /> Loading</> : 'Show charts'}
          </button>
        </div>
      </Panel>

      {error && <ErrorNote error={error} onRetry={() => load(input)} />}
      {busy && !data && <Panel><Loading>Loading price history</Loading></Panel>}

      {!data && !busy && !error && (
        <Panel>
          <Empty title="Pick a stock">
            Type an NSE ticker above, or click any ticker in the Overview or Signals tabs
            to open it here.
          </Empty>
        </Panel>
      )}

      {data && <Detail data={data} />}
    </div>
  )
}

function Detail({ data }) {
  const s = data.series
  const last = s[s.length - 1]
  const prev = s[s.length - 2]
  const changePct = prev ? ((last.close - prev.close) / prev.close) * 100 : null
  const w = data.windows

  const latestSma = data.crossovers.sma[0]
  const latestMacd = data.crossovers.macd[0]

  return (
    <>
      <Panel title={`${data.symbol} - ${data.company}`} note={data.industry}>
        <div className="summary-row" style={{ fontSize: 15 }}>
          <span className="num" style={{ fontSize: 22, fontWeight: 600 }}>₹{money(last.close)}</span>
          <Change value={changePct} />
          <span style={{ color: 'var(--text-faint)', fontSize: 13 }}>
            close of {prettyDate(last.date)}
          </span>
        </div>
        <div className="summary-row" style={{ marginTop: 12, fontSize: 13 }}>
          <LatestSignal label={`SMA ${w.short}/${w.long}`} mark={latestSma} />
          <LatestSignal label={`MACD ${w.fast}/${w.slow}/${w.signal}`} mark={latestMacd} />
        </div>
      </Panel>

      <Panel title="Close and moving averages"
             note={`${s.length} sessions - markers show crossovers with their angle`}>
        <LineChart series={s} keys={[
          { key: 'close', color: 'var(--text-dim)', width: 1.2, faded: true, label: 'Close' },
          { key: 'sma_long', color: 'var(--down)', width: 1.8, label: `SMA ${w.long}` },
          { key: 'sma_short', color: 'var(--accent)', width: 1.8, label: `SMA ${w.short}` },
        ]} marks={data.crossovers.sma} height={290} />
      </Panel>

      <Panel title={`MACD ${w.fast}, ${w.slow}, ${w.signal}`}
             note="Histogram is MACD minus signal">
        <LineChart series={s} keys={[
          { key: 'signal', color: 'var(--down)', width: 1.8, label: 'Signal' },
          { key: 'macd', color: 'var(--accent)', width: 1.8, label: 'MACD' },
        ]} marks={data.crossovers.macd} height={220} histogram="hist" zeroLine />
      </Panel>
    </>
  )
}

function LatestSignal({ label, mark }) {
  if (!mark) return <span style={{ color: 'var(--text-faint)' }}>{label}: no crossover on record</span>
  const bull = mark.crossover === 'bullish'
  return (
    <span>
      {label}:{' '}
      <b className={bull ? 'up' : 'down'}>{bull ? 'bullish' : 'bearish'}</b>{' '}
      on {prettyDate(mark.date)}
      <span style={{ color: 'var(--text-faint)' }}>
        {' '}at {mark.angle?.toFixed(1)}°
      </span>
    </span>
  )
}

/* A small hand-drawn SVG chart. No charting library, so nothing extra to
   install and the colours stay on the theme. */
function LineChart({ series, keys, marks = [], height = 280, histogram, zeroLine }) {
  const W = 1000
  const pad = { top: 14, right: 58, bottom: 26, left: 8 }

  const all = series.flatMap((d) => keys.map((k) => d[k.key]))
    .concat(histogram ? series.map((d) => d[histogram]) : [])
    .filter((v) => v != null)
  if (!all.length) return null

  let lo = Math.min(...all)
  let hi = Math.max(...all)
  if (zeroLine) { lo = Math.min(lo, 0); hi = Math.max(hi, 0) }
  const span = hi - lo || 1

  const x = (i) => pad.left + (i / Math.max(1, series.length - 1)) * (W - pad.left - pad.right)
  const y = (v) => pad.top + (1 - (v - lo) / span) * (height - pad.top - pad.bottom)

  const path = (key) => {
    let d = ''
    let open = false
    series.forEach((pt, i) => {
      const v = pt[key]
      if (v == null) { open = false; return }
      d += `${open ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)} `
      open = true
    })
    return d.trim()
  }

  const posOf = new Map(series.map((pt, i) => [pt.date, i]))
  const ticks = zeroLine ? [lo, 0, hi] : [lo, lo + span / 2, hi]
  const barW = Math.max(1, ((W - pad.left - pad.right) / series.length) * 0.6)

  return (
    <>
      <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height} role="img"
           aria-label={keys.map((k) => k.label).join(', ')}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={pad.left} x2={W - pad.right} y1={y(t)} y2={y(t)}
                  stroke={t === 0 && zeroLine ? 'var(--line)' : 'var(--line-soft)'} strokeWidth="1" />
            <text x={W - pad.right + 8} y={y(t) + 4} fill="var(--text-faint)"
                  fontSize="11" fontFamily="var(--font-num)">{t.toFixed(2)}</text>
          </g>
        ))}

        {histogram && series.map((pt, i) => {
          const v = pt[histogram]
          if (v == null) return null
          const y0 = y(0)
          const y1 = y(v)
          return <rect key={i} x={x(i) - barW / 2} y={Math.min(y0, y1)} width={barW}
                       height={Math.max(1, Math.abs(y1 - y0))}
                       fill={v >= 0 ? 'var(--up)' : 'var(--down)'} opacity="0.32" />
        })}

        {keys.map((k) => (
          <path key={k.key} d={path(k.key)} fill="none" stroke={k.color}
                strokeWidth={k.width} opacity={k.faded ? 0.5 : 1} />
        ))}

        {marks.map((m) => {
          const i = posOf.get(m.date)
          if (i == null) return null
          const pt = series[i]
          const v = pt[keys[keys.length - 1].key]
          if (v == null) return null
          const bull = m.crossover === 'bullish'
          const r = 3 + Math.min(4, Math.abs(m.angle || 0) / 12)
          return (
            <g key={m.date}>
              <circle cx={x(i)} cy={y(v)} r={r}
                      fill={bull ? 'var(--up)' : 'var(--down)'}
                      stroke="var(--surface)" strokeWidth="1.5" />
              <title>{`${bull ? 'Bullish' : 'Bearish'} ${prettyDate(m.date)} - ${m.angle?.toFixed(1)}° (${m.grade})`}</title>
            </g>
          )
        })}

        <text x={pad.left} y={height - 6} fill="var(--text-faint)" fontSize="11">
          {prettyDate(series[0].date)}
        </text>
        <text x={W - pad.right} y={height - 6} fill="var(--text-faint)" fontSize="11" textAnchor="end">
          {prettyDate(series[series.length - 1].date)}
        </text>
      </svg>

      <div className="summary-row" style={{ marginTop: 10, fontSize: 12.5 }}>
        {keys.map((k) => <Legend key={k.key} color={k.color} label={k.label} faded={k.faded} />)}
        {marks.length > 0 && (
          <span style={{ color: 'var(--text-faint)' }}>
            {marks.length} crossover{marks.length > 1 ? 's' : ''} marked - dot size tracks angle
          </span>
        )}
      </div>
    </>
  )
}

function Legend({ color, label, faded }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
      <i style={{ width: 16, height: 2, background: color, borderRadius: 2,
                  opacity: faded ? 0.5 : 1, display: 'inline-block' }} />
      {label}
    </span>
  )
}
