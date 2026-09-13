// Every call goes through /api, which Vite proxies to FastAPI on port 8000.
// See vite.config.js if you move the backend.

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new Error(
      'Cannot reach the backend. Start it with: uvicorn app.main:app --reload --port 8000'
    )
  }

  let body = null
  try {
    body = await res.json()
  } catch {
    /* empty or non-JSON response */
  }

  if (!res.ok) {
    throw new Error(detailToMessage(body) || `Request failed (${res.status})`)
  }
  return body
}

// FastAPI returns validation errors as an array of objects. Flatten them into
// something a person can read.
function detailToMessage(body) {
  const d = body?.detail
  if (!d) return null
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    return d
      .map((e) => {
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : ''
        return field ? `${field}: ${e.msg}` : e.msg
      })
      .join('. ')
  }
  return JSON.stringify(d)
}

export const api = {
  status: () => request('/api/status'),
  strategies: () => request('/api/strategies'),
  market: () => request('/api/market'),
  universe: () => request('/api/universe'),
  stock: (symbol, params = {}) => {
    const q = new URLSearchParams(params).toString()
    return request(`/api/stock/${encodeURIComponent(symbol)}${q ? `?${q}` : ''}`)
  },
  scan: (params) =>
    request('/api/signals/scan', { method: 'POST', body: JSON.stringify(params) }),
  refresh: () => request('/api/refresh', { method: 'POST' }),
  warmCache: (days = 120) =>
    request(`/api/cache/warm?days=${days}`, { method: 'POST' }),
}
