import React from 'react'

/* -------------------------------------------------------------- layout -- */

export function Panel({ title, note, children, bodyless = false }) {
  return (
    <section className="panel">
      {(title || note) && (
        <header className="panel-head">
          {title && <h2>{title}</h2>}
          {note && <span className="note">{note}</span>}
        </header>
      )}
      {bodyless ? children : <div className="panel-body">{children}</div>}
    </section>
  )
}

export function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function NumberField({ label, hint, value, onChange, min, max, step = 1 }) {
  return (
    <Field label={label} hint={hint}>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const raw = e.target.value
          onChange(raw === '' ? '' : Number(raw))
        }}
      />
    </Field>
  )
}

/* -------------------------------------------------------------- states -- */

export function Loading({ children = 'Loading' }) {
  return (
    <div className="state">
      <span className="spinner" /> <span style={{ marginLeft: 8 }}>{children}</span>
    </div>
  )
}

export function ErrorNote({ error, onRetry }) {
  if (!error) return null
  return (
    <div className="alert">
      <b>That didn't work.</b> {String(error.message || error)}
      {onRetry && (
        <div>
          <button className="btn btn-quiet" style={{ marginTop: 10 }} onClick={onRetry}>
            Try again
          </button>
        </div>
      )}
    </div>
  )
}

export function Empty({ title, children, action }) {
  return (
    <div className="state">
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  )
}

/* ---------------------------------------------------------------- bits -- */

export function CrossoverTag({ kind }) {
  const bull = kind === 'bullish'
  return (
    <span className={bull ? 'tag tag-bull' : 'tag tag-bear'}>
      {bull ? '▲' : '▼'} {bull ? 'Bullish' : 'Bearish'}
    </span>
  )
}

export function Change({ value, suffix = '%' }) {
  if (value == null) return <span className="num">—</span>
  const cls = value > 0 ? 'up' : value < 0 ? 'down' : ''
  return (
    <span className={`num ${cls}`}>
      {value > 0 ? '+' : ''}
      {value.toFixed(2)}
      {suffix}
    </span>
  )
}

/* Crossover strength, shown as a number and as the shape it describes: two
   rays meeting at the measured angle. The drawing is capped at 60 degrees so a
   very steep signal stays legible, but the printed number is always exact. */
export function AngleCell({ angle, grade, percentile }) {
  if (angle == null) return <span className="num">—</span>

  const size = 30
  const drawn = Math.min(60, Math.abs(angle))
  const rad = (drawn * Math.PI) / 180
  const len = 22
  const ox = 3
  const oy = size / 2
  const up = angle >= 0
  const ey = up ? oy - Math.sin(rad) * len : oy + Math.sin(rad) * len
  const ex = ox + Math.cos(rad) * len

  const tone = up ? 'var(--up)' : 'var(--down)'
  const title = `${angle.toFixed(2)}° — ${grade}${
    percentile != null ? `, steeper than ${percentile.toFixed(0)}% of this scan` : ''
  }`

  return (
    <span className="angle-cell" title={title}>
      <svg width={size} height={size / 1.6} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <line x1={ox} y1={oy} x2={ox + len} y2={oy}
              stroke="var(--text-faint)" strokeWidth="1.6" strokeLinecap="round" />
        <line x1={ox} y1={oy} x2={ex} y2={ey}
              stroke={tone} strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      <span className={`angle-value grade-${grade}`}>{angle.toFixed(1)}°</span>
    </span>
  )
}

/* ---------------------------------------------------------- formatting -- */

const RUPEE = new Intl.NumberFormat('en-IN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function money(v) {
  return v == null ? '—' : RUPEE.format(v)
}

export function compact(v) {
  if (v == null) return '—'
  if (v >= 1e7) return `${(v / 1e7).toFixed(2)} Cr`
  if (v >= 1e5) return `${(v / 1e5).toFixed(2)} L`
  return new Intl.NumberFormat('en-IN').format(v)
}

// '2026-09-11' -> '11 Sep 2026'. Built by hand so it never depends on the
// browser's locale settings.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function prettyDate(iso, { withYear = true } = {}) {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-').map(Number)
  if (!y || !m || !d) return iso
  return `${d} ${MONTHS[m - 1]}${withYear ? ` ${y}` : ''}`
}

export function relativeDays(n) {
  if (n == null) return ''
  if (n === 0) return 'today'
  if (n === 1) return '1 session ago'
  return `${n} sessions ago`
}
