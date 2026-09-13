import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import FreshnessBar from '../components/FreshnessBar.jsx'
import {
  Panel, Field, ErrorNote, Empty, Loading,
  CrossoverTag, Change, AngleCell, money, prettyDate, relativeDays,
} from '../components/ui.jsx'

/*
  Nothing in this file knows what an SMA or a MACD is.

  The backend describes each strategy - its inputs and its result columns - and
  this renders whatever it is given. Adding an indicator means writing a class
  in backend/app/strategies.py. No changes here.
*/

export default function SignalsTab({ onPickSymbol }) {
  const [catalog, setCatalog] = useState(null)
  const [spec, setSpec] = useState(null)
  const [values, setValues] = useState({})
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.strategies()
      .then((c) => { setCatalog(c); pick(c, c.default) })
      .catch(setError)
  }, [])

  function pick(c, id) {
    const found = c.strategies.find((s) => s.id === id)
    setSpec(found)
    setValues(Object.fromEntries(found.params.map((p) => [p.key, p.default])))
    setData(null)
    setError(null)
  }

  const invalid = useMemo(() => validate(spec, values), [spec, values])

  async function run() {
    if (!spec || invalid) return
    setBusy(true); setError(null)
    try {
      setData(await api.scan({ strategy: spec.id, params: values }))
    } catch (e) {
      setError(e); setData(null)
    } finally {
      setBusy(false)
    }
  }

  if (!catalog && !error) return <Panel><Loading>Loading strategies</Loading></Panel>
  if (error && !catalog) return <ErrorNote error={error} />
  if (!spec) return null

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      {/* After a local refresh pulls new sessions, re-run so the table reflects them. */}
      <FreshnessBar onRefreshed={(r) => { if (r.downloaded > 0 && data) run() }} />

      <Panel title="Strategy" note="More can be added without touching the frontend">
        <div className="segmented" role="radiogroup" aria-label="Strategy">
          {catalog.strategies.map((s) => (
            <button key={s.id} role="radio" aria-checked={s.id === spec.id}
                    onClick={() => pick(catalog, s.id)}>
              <b>{s.label}</b>
              <span>{s.tagline}</span>
            </button>
          ))}
        </div>
        <p className="explainer">{spec.explainer}</p>
      </Panel>

      <Panel title="Settings" note="Nifty 100 - daily closes">
        <div className="controls">
          {spec.params.map((p) => (
            <ParamInput key={p.key} param={p} value={values[p.key]}
              onChange={(v) => setValues((old) => ({ ...old, [p.key]: v }))} />
          ))}
          <button className="btn" onClick={run} disabled={busy || !!invalid}>
            {busy ? <><span className="spinner" /> Scanning</> : 'Generate signals'}
          </button>
        </div>
        {invalid && <p className="form-error">{invalid}</p>}
        {busy && (
          <p className="form-note">
            The first scan of the day downloads the sessions you are missing from NSE and
            can take a minute. Afterwards it reads your local cache and returns at once.
          </p>
        )}
      </Panel>

      {error && <ErrorNote error={error} onRetry={run} />}

      {!data && !busy && !error && (
        <Panel>
          <Empty title="No scan yet"
                 action={<button className="btn" onClick={run}>Generate signals</button>}>
            {spec.tagline}. Run the scan to see which Nifty 100 stocks crossed in the
            last {values.lookback_days} sessions, most recent first.
          </Empty>
        </Panel>
      )}

      {busy && !data && <Panel><Loading>Fetching sessions from NSE</Loading></Panel>}
      {data && <Results spec={spec} data={data} onPickSymbol={onPickSymbol} />}
    </div>
  )
}

/* --------------------------------------------------------------- inputs -- */

function ParamInput({ param, value, onChange }) {
  if (param.kind === 'bool') {
    return (
      <label className="check">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        {param.label}
      </label>
    )
  }
  if (param.kind === 'choice') {
    return (
      <Field label={param.label} hint={param.hint}>
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          {param.choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </Field>
    )
  }
  return (
    <Field label={param.label} hint={param.hint}>
      <input type="number" value={value}
        min={param.min ?? undefined} max={param.max ?? undefined}
        step={param.kind === 'float' ? 0.5 : 1}
        onChange={(e) => {
          const raw = e.target.value
          onChange(raw === '' ? '' : Number(raw))
        }} />
    </Field>
  )
}

// Catches obvious mistakes in the browser so you do not wait for a round trip.
// The backend validates properly regardless.
function validate(spec, values) {
  if (!spec) return null
  for (const p of spec.params) {
    if (p.kind === 'bool' || p.kind === 'choice') continue
    const v = values[p.key]
    if (v === '' || v == null || Number.isNaN(v)) return `${p.label} needs a value.`
    if (p.min != null && v < p.min) return `${p.label} must be at least ${p.min}.`
    if (p.max != null && v > p.max) return `${p.label} can be at most ${p.max}.`
  }
  const pairs = [
    ['short_window', 'long_window', 'Short SMA must be smaller than long SMA.'],
    ['fast_span', 'slow_span', 'Fast EMA must be smaller than slow EMA.'],
  ]
  for (const [a, b, msg] of pairs) {
    if (values[a] != null && values[b] != null && values[a] >= values[b]) return msg
  }
  return null
}

/* -------------------------------------------------------------- results -- */

const alignRight = (kind) => ['money', 'percent', 'number', 'angle'].includes(kind)

function Results({ spec, data, onPickSymbol }) {
  const { results, summary } = data

  if (!results.length) {
    return (
      <Panel title="Results">
        <Empty title="No crossovers in that window">
          None of the {summary.scanned} stocks scanned crossed in the last{' '}
          {data.params.lookback_days} sessions. Widen Lookback Days, lower Min angle,
          or move the two lines closer together so they cross more often.
        </Empty>
      </Panel>
    )
  }

  return (
    <>
      <Panel title="Crossovers by day"
             note={`${prettyDate(summary.history_from)} - ${prettyDate(summary.history_to)}`}>
        <Timeline results={results} />
        <div className="summary-row" style={{ marginTop: 16 }}>
          <span><b className="up">{summary.bullish}</b> bullish</span>
          <span><b className="down">{summary.bearish}</b> bearish</span>
          <span><b>{summary.scanned}</b> stocks scanned</span>
          <span><b>{summary.trading_days_loaded}</b> sessions loaded</span>
          {summary.whipsaw > 0 && <span><b>{summary.whipsaw}</b> flagged choppy</span>}
          <span style={{ marginLeft: 'auto' }}>
            <Freshness summary={summary} />
          </span>
        </div>
      </Panel>

      <Panel title="Ranked signals" note="Most recent crossover first" bodyless>
        <div className="table-scroll">
          <table className="data">
            <thead>
              <tr>
                {spec.columns.map((c) => (
                  <th key={c.key} title={c.hint || undefined}
                      className={c.key === 'rank' ? 'rank' : alignRight(c.kind) ? 'num' : undefined}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.map((row) => (
                <tr key={row.symbol}>
                  {spec.columns.map((c) => (
                    <Cell key={c.key} col={c} row={row} onPickSymbol={onPickSymbol} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <p className="footnote">
        <b>Angle</b> is the degrees between the two lines where they crossed, measured as
        percent of price per day so a 2,800-rupee stock and a 95-rupee one stay
        comparable. Steepness is graded against the rest of this scan rather than a fixed
        threshold, because every indicator sits on its own scale.{' '}
        <b>Gap now</b> is how far apart the lines have moved since, signed so positive
        always means the signal is still working. Rows marked <b>choppy</b> crossed three
        or more times in the window, which usually means the two lines are overlapping
        rather than trending.
        {summary.no_data?.length > 0 && (
          <> {summary.no_data.length} symbol{summary.no_data.length > 1 ? 's' : ''} had no
          data in this window and were skipped: {summary.no_data.join(', ')}.</>
        )}
      </p>
    </>
  )
}

function Cell({ col, row, onPickSymbol }) {
  const v = row[col.key]

  switch (col.kind) {
    case 'number':
      if (col.key === 'rank') return <td className="rank">{v}</td>
      return <td className="num">{v == null ? '-' : v}</td>
    case 'money':
      return <td className="num">{money(v)}</td>
    case 'percent':
      return <td><Change value={v} /></td>
    case 'angle':
      return (
        <td className="num">
          <AngleCell angle={v} grade={row.angle_grade} percentile={row.angle_percentile} />
        </td>
      )
    case 'date':
      return (
        <td>
          {prettyDate(v, { withYear: false })}
          <span className="muted-inline">{relativeDays(row.days_since)}</span>
        </td>
      )
    case 'tag':
      return (
        <td>
          <CrossoverTag kind={v} />
          {row.whipsaw && (
            <span className="tag-warn" title={`Crossed ${row.crossings} times in this window`}>
              choppy
            </span>
          )}
        </td>
      )
    default:
      if (col.key === 'symbol') {
        return (
          <td className="ticker">
            <button className="linkish ticker" onClick={() => onPickSymbol(v)}>{v}</button>
          </td>
        )
      }
      if (col.key === 'company') return <td className="company" title={v}>{v}</td>
      return <td>{v ?? '-'}</td>
  }
}

/* Every scan checks NSE for sessions published since the last one, so this
   line is how you confirm the data actually moved. */
function Freshness({ summary }) {
  const fresh = summary.days_downloaded > 0
  const snapshot = (summary.data_source || '').startsWith('snapshot')

  return (
    <span className="freshness">
      <b>Prices to {prettyDate(summary.history_to)}</b>
      <span className={fresh ? 'freshness-new' : ''}>
        {snapshot
          ? 'from the prebuilt snapshot'
          : fresh
            ? `${summary.days_downloaded} new session${summary.days_downloaded > 1 ? 's' : ''} pulled from NSE`
            : 'already up to date'}
      </span>
      <span style={{ color: 'var(--text-faint)' }}>{summary.elapsed_seconds}s</span>
    </span>
  )
}

/* ------------------------------------------------------------- timeline -- */

function Timeline({ results }) {
  const byDay = useMemo(() => {
    const map = new Map()
    for (const r of results) {
      const slot = map.get(r.crossover_date) || { bull: 0, bear: 0 }
      slot[r.crossover === 'bullish' ? 'bull' : 'bear'] += 1
      map.set(r.crossover_date, slot)
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [results])

  const peak = Math.max(1, ...byDay.map(([, v]) => v.bull + v.bear))

  return (
    <div>
      <div className="timeline" role="img" aria-label={`Crossovers across ${byDay.length} sessions`}>
        {byDay.map(([day, v]) => (
          <div className="timeline-col" key={day}
               title={`${prettyDate(day)} - ${v.bull} bullish, ${v.bear} bearish`}>
            {v.bull > 0 && <i className="b" style={{ height: `${(v.bull / peak) * 42}px` }} />}
            {v.bear > 0 && <i className="s" style={{ height: `${(v.bear / peak) * 42}px` }} />}
          </div>
        ))}
      </div>
      {byDay.length > 0 && (
        <div className="timeline-axis">
          <span>{prettyDate(byDay[0][0])}</span>
          <span>{prettyDate(byDay[byDay.length - 1][0])}</span>
        </div>
      )}
    </div>
  )
}
