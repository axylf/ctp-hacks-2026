import { useState } from 'react'
import './App.css'

function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [result, setResult] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    if (!selectedFile) {
      setError('Please choose an image first.')
      return
    }

    const formData = new FormData()
    formData.append('image', selectedFile)

    setLoading(true)
    setError('')
    setResult('')

    try {
      const response = await fetch('http://localhost:5000/api/extract-text', {
        method: 'POST',
        body: formData,
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'OCR request failed')
      }

      setResult(data.text || 'No text found in image.')
      console.log('OCR response:', data)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Something went wrong'
      setError(message)
      console.error('OCR error:', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="ocr-page">
      <div className="ocr-card">
        <h1>OCR Image Test</h1>

        <form onSubmit={handleSubmit} className="ocr-form">
          <input
            type="file"
            accept="image/*"
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
          />

          <button type="submit" disabled={loading || !selectedFile}>
            {loading ? 'Processing...' : 'Extract Text'}
          </button>
        </form>

        {error && <p className="error-message">{error}</p>}

        <div className="result-box">
          <h2>Output</h2>
          <pre>{result || 'No OCR text yet.'}</pre>
        </div>
      </div>
    </main>
  )
}

export default App
