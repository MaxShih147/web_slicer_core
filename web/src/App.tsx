import { useState, useCallback, useRef } from 'react'

const API_BASE = 'http://127.0.0.1:5179'

type Status = 'idle' | 'uploading' | 'slicing' | 'done' | 'error'

interface JobStatus {
  job_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  layer_count: number | null
  error: string | null
}

function App() {
  const [file, setFile] = useState<File | null>(null)
  const [status, setStatus] = useState<Status>('idle')
  const [statusMessage, setStatusMessage] = useState('Select an STL file to slice')
  const [jobId, setJobId] = useState<string | null>(null)
  const [layerCount, setLayerCount] = useState(0)
  const [currentLayer, setCurrentLayer] = useState(0)
  const [layerUrl, setLayerUrl] = useState<string | null>(null)
  const pollingRef = useRef<number | null>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0]
    if (selected) {
      setFile(selected)
      setStatusMessage(`Selected: ${selected.name}`)
      // Reset previous job state
      setJobId(null)
      setLayerCount(0)
      setCurrentLayer(0)
      setLayerUrl(null)
      setStatus('idle')
    }
  }

  const loadLayer = useCallback(async (jobIdParam: string, idx: number) => {
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${jobIdParam}/layers/${idx}.png`)
      if (!response.ok) {
        console.error('Failed to load layer:', response.status)
        return
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      // Revoke previous URL to avoid memory leaks
      if (layerUrl) {
        URL.revokeObjectURL(layerUrl)
      }
      setLayerUrl(url)
      setCurrentLayer(idx)
    } catch (err) {
      console.error('Error loading layer:', err)
    }
  }, [layerUrl])

  const pollJobStatus = useCallback(async (jobIdParam: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${jobIdParam}`)
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const data: JobStatus = await response.json()
      console.log('Job status:', data)

      if (data.status === 'pending' || data.status === 'processing') {
        setStatusMessage(`Slicing in progress... (${data.status})`)
        // Continue polling
        pollingRef.current = window.setTimeout(() => pollJobStatus(jobIdParam), 1000)
      } else if (data.status === 'completed') {
        setStatus('done')
        setLayerCount(data.layer_count ?? 0)
        setStatusMessage(`Slicing complete! ${data.layer_count} layers generated.`)
        // Load first layer
        if (data.layer_count && data.layer_count > 0) {
          loadLayer(jobIdParam, 0)
        }
      } else if (data.status === 'failed') {
        setStatus('error')
        setStatusMessage(`Slicing failed: ${data.error ?? 'Unknown error'}`)
      }
    } catch (err) {
      console.error('Polling error:', err)
      setStatus('error')
      setStatusMessage(`Error checking job status: ${err}`)
    }
  }, [loadLayer])

  const handleSlice = async () => {
    if (!file) return

    // Clear any existing polling
    if (pollingRef.current) {
      clearTimeout(pollingRef.current)
    }

    setStatus('uploading')
    setStatusMessage('Uploading file...')
    setLayerUrl(null)
    setLayerCount(0)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch(`${API_BASE}/api/jobs`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `HTTP ${response.status}`)
      }

      const data = await response.json()
      console.log('Job created:', data)

      setJobId(data.job_id)
      setStatus('slicing')
      setStatusMessage('Slicing started...')

      // Start polling for status
      pollJobStatus(data.job_id)
    } catch (err) {
      console.error('Upload error:', err)
      setStatus('error')
      setStatusMessage(`Upload failed: ${err}`)
    }
  }

  const goToLayer = (idx: number) => {
    if (jobId && idx >= 0 && idx < layerCount) {
      loadLayer(jobId, idx)
    }
  }

  const canSlice = file && (status === 'idle' || status === 'done' || status === 'error')
  const isWorking = status === 'uploading' || status === 'slicing'

  return (
    <div className="app">
      <h1>Web Slicer</h1>

      <div className="upload-section">
        <div className="file-input">
          <input
            type="file"
            accept=".stl"
            onChange={handleFileChange}
            disabled={isWorking}
          />
        </div>
        <button
          className="slice-btn"
          onClick={handleSlice}
          disabled={!canSlice}
        >
          {isWorking ? 'Working...' : 'Slice'}
        </button>
      </div>

      <div className={`status ${status === 'error' ? 'error' : status === 'done' ? 'done' : ''}`}>
        {statusMessage}
      </div>

      <div className="viewer">
        {layerCount > 0 && (
          <>
            <div className="layer-nav">
              <button
                className="nav-btn"
                onClick={() => goToLayer(currentLayer - 1)}
                disabled={currentLayer <= 0}
              >
                Prev
              </button>
              <span className="layer-info">
                Layer {currentLayer + 1} / {layerCount}
              </span>
              <button
                className="nav-btn"
                onClick={() => goToLayer(currentLayer + 1)}
                disabled={currentLayer >= layerCount - 1}
              >
                Next
              </button>
            </div>
            <input
              type="range"
              className="layer-slider"
              min={0}
              max={layerCount - 1}
              value={currentLayer}
              onChange={(e) => goToLayer(parseInt(e.target.value, 10))}
            />
          </>
        )}
        <div className="layer-image">
          {layerUrl ? (
            <img src={layerUrl} alt={`Layer ${currentLayer}`} />
          ) : (
            <div className="placeholder">
              {status === 'done' && layerCount === 0
                ? 'No layers generated'
                : 'Layer preview will appear here'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default App
