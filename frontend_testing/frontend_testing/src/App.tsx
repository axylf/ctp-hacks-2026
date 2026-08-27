import { useState } from 'react'
import './App.css'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY

function App() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState('')
  const [status, setStatus] = useState('')

  const handleSupabaseTest = async () => {
    setLoading(true)
    setError('')
    setResult('')
    setStatus('Testing Supabase connection...')

    try {
      if (!supabaseUrl || !supabaseKey) {
        throw new Error('Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY in the frontend .env file.')
      }

      const response = await fetch(`${supabaseUrl}/rest/v1/supabase_test`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'apikey': supabaseKey,
          'Authorization': `Bearer ${supabaseKey}`,
        },
        body: JSON.stringify({
          message: `Frontend test @ ${new Date().toISOString()}`,
          created_at: new Date().toISOString(),
        }),
      })

      const text = await response.text()
      const data = text ? JSON.parse(text) : null

      if (!response.ok) {
        throw new Error(data?.message || `Supabase request failed (${response.status})`)
      }

      setStatus('Supabase write succeeded.')
      setResult(JSON.stringify(data, null, 2))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Something went wrong'
      setError(message)
      setStatus('Supabase connection failed.')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="ocr-page">
      <div className="ocr-card">
        <h1>Supabase Test</h1>

        <button type="button" onClick={handleSupabaseTest} disabled={loading} className="primary-button">
          {loading ? 'Testing...' : 'Run Supabase Test'}
        </button>

        {status && <p className="status-text">{status}</p>}
        {error && <p className="error-message">{error}</p>}

        <div className="result-box">
          <h2>Response</h2>
          <pre>{result || 'No response yet.'}</pre>
        </div>
      </div>
    </main>
  )
}

export default App
