import { useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function App() {
  const [query, setQuery] = useState('')
  const [answer, setAnswer] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setAnswer(null)
    try {
      const res = await fetch(`${API_BASE}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setAnswer(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: '40px auto', padding: 16, fontFamily: 'sans-serif' }}>
      <h1>А-Помощь (skeleton)</h1>
      <p style={{ color: '#666' }}>API: {API_BASE}</p>

      <form onSubmit={handleSubmit}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Задай вопрос…"
          style={{ width: '100%', padding: 12, fontSize: 16 }}
          maxLength={200}
        />
        <button type="submit" disabled={loading || !query} style={{ marginTop: 8, padding: '10px 16px' }}>
          {loading ? 'Думаю…' : 'Спросить'}
        </button>
      </form>

      {error && (
        <div style={{ marginTop: 16, color: 'crimson' }}>
          Ошибка: {error}
        </div>
      )}

      {answer && (
        <div style={{ marginTop: 16, padding: 16, border: '1px solid #ddd', borderRadius: 8 }}>
          <p>{answer.lead}</p>
          {answer.sources?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <strong>Источники:</strong>
              <ul>
                {answer.sources.map((s) => (
                  <li key={s.article_id}>
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.title}
                    </a>{' '}
                    <span style={{ color: '#999' }}>({s.category})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default App