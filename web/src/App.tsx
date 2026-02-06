import { useState, useCallback, useRef } from 'react'
import { STLViewer } from './STLViewer'

const API_BASE = 'http://127.0.0.1:5179'

type Status = 'idle' | 'uploading' | 'slicing' | 'done' | 'error'

interface JobStatus {
  job_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  layer_count: number | null
  error: string | null
  has_support_mesh: boolean
}

interface SLAConfig {
  layer_height: number
  exposure_time: number
  initial_exposure_time: number
  supports_enable: boolean
  support_head_front_diameter: number
  support_head_penetration: number
  support_pillar_diameter: number
  support_points_density_relative: number
  support_object_elevation: number
  support_critical_angle: number
  pad_enable: boolean
}

const DEFAULT_CONFIG: SLAConfig = {
  layer_height: 0.05,
  exposure_time: 10.0,
  initial_exposure_time: 15.0,
  supports_enable: false,
  support_head_front_diameter: 0.4,
  support_head_penetration: 0.2,
  support_pillar_diameter: 1.0,
  support_points_density_relative: 100,
  support_object_elevation: 5.0,
  support_critical_angle: 45.0,
  pad_enable: false,
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
  const [config, setConfig] = useState<SLAConfig>({ ...DEFAULT_CONFIG })
  const [configExpanded, setConfigExpanded] = useState(false)
  const [hasSupportMesh, setHasSupportMesh] = useState(false)
  const [viewMode, setViewMode] = useState<'3d' | 'layers'>('3d')
  const [localModelUrl, setLocalModelUrl] = useState<string | null>(null)

  const updateConfig = <K extends keyof SLAConfig>(key: K, value: SLAConfig[K]) => {
    setConfig(prev => ({ ...prev, [key]: value }))
  }

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
      setHasSupportMesh(false)
      // Create local URL for immediate 3D preview
      if (localModelUrl) {
        URL.revokeObjectURL(localModelUrl)
      }
      setLocalModelUrl(URL.createObjectURL(selected))
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
        setHasSupportMesh(data.has_support_mesh ?? false)
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
    setHasSupportMesh(false)
    setViewMode('3d')

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('config', JSON.stringify(config))

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

      <div className="config-panel">
        <button
          className="config-toggle"
          onClick={() => setConfigExpanded(!configExpanded)}
        >
          {configExpanded ? '▼' : '▶'} Slicing Config
        </button>

        {configExpanded && (
          <div className="config-content">
            <div className="config-group">
              <h3>Layer</h3>
              <label>
                Layer Height
                <select
                  value={config.layer_height}
                  onChange={e => updateConfig('layer_height', parseFloat(e.target.value))}
                  disabled={isWorking}
                >
                  <option value={0.025}>0.025 mm</option>
                  <option value={0.05}>0.05 mm</option>
                  <option value={0.1}>0.1 mm</option>
                </select>
              </label>
            </div>

            <div className="config-group">
              <h3>Exposure</h3>
              <label>
                Exposure Time: {config.exposure_time}s
                <input
                  type="range"
                  min={1}
                  max={30}
                  step={0.5}
                  value={config.exposure_time}
                  onChange={e => updateConfig('exposure_time', parseFloat(e.target.value))}
                  disabled={isWorking}
                />
              </label>
              <label>
                Initial Exposure: {config.initial_exposure_time}s
                <input
                  type="range"
                  min={5}
                  max={60}
                  step={1}
                  value={config.initial_exposure_time}
                  onChange={e => updateConfig('initial_exposure_time', parseFloat(e.target.value))}
                  disabled={isWorking}
                />
              </label>
            </div>

            <div className="config-group">
              <h3>Supports</h3>
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={config.supports_enable}
                  onChange={e => updateConfig('supports_enable', e.target.checked)}
                  disabled={isWorking}
                />
                Enable Supports
              </label>
              {config.supports_enable && (
                <>
                  <label>
                    Head Diameter: {config.support_head_front_diameter}mm
                    <input
                      type="range"
                      min={0.2}
                      max={1.0}
                      step={0.1}
                      value={config.support_head_front_diameter}
                      onChange={e => updateConfig('support_head_front_diameter', parseFloat(e.target.value))}
                      disabled={isWorking}
                    />
                  </label>
                  <label>
                    Head Penetration: {config.support_head_penetration}mm
                    <input
                      type="range"
                      min={0.1}
                      max={0.5}
                      step={0.05}
                      value={config.support_head_penetration}
                      onChange={e => updateConfig('support_head_penetration', parseFloat(e.target.value))}
                      disabled={isWorking}
                    />
                  </label>
                  <label>
                    Pillar Diameter: {config.support_pillar_diameter}mm
                    <input
                      type="range"
                      min={0.5}
                      max={2.0}
                      step={0.1}
                      value={config.support_pillar_diameter}
                      onChange={e => updateConfig('support_pillar_diameter', parseFloat(e.target.value))}
                      disabled={isWorking}
                    />
                  </label>
                  <label>
                    Density: {config.support_points_density_relative}%
                    <input
                      type="range"
                      min={50}
                      max={200}
                      step={10}
                      value={config.support_points_density_relative}
                      onChange={e => updateConfig('support_points_density_relative', parseInt(e.target.value, 10))}
                      disabled={isWorking}
                    />
                  </label>
                  <label>
                    Object Elevation: {config.support_object_elevation}mm
                    <input
                      type="range"
                      min={0}
                      max={10}
                      step={0.1}
                      value={config.support_object_elevation}
                      onChange={e => updateConfig('support_object_elevation', parseFloat(e.target.value))}
                      disabled={isWorking}
                    />
                  </label>
                  <label>
                    Critical Angle: {config.support_critical_angle}°
                    <input
                      type="range"
                      min={0}
                      max={90}
                      step={1}
                      value={config.support_critical_angle}
                      onChange={e => updateConfig('support_critical_angle', parseFloat(e.target.value))}
                      disabled={isWorking}
                    />
                  </label>
                </>
              )}
            </div>

            <div className="config-group">
              <h3>Pad</h3>
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={config.pad_enable}
                  onChange={e => updateConfig('pad_enable', e.target.checked)}
                  disabled={isWorking}
                />
                Enable Pad
              </label>
            </div>
          </div>
        )}
      </div>

      <div className={`status ${status === 'error' ? 'error' : status === 'done' ? 'done' : ''}`}>
        {statusMessage}
      </div>

      {(localModelUrl || (status === 'done' && jobId)) && (
        <div className="view-controls">
          {status === 'done' && (
            <div className="view-toggle">
              <button
                className={`toggle-btn ${viewMode === '3d' ? 'active' : ''}`}
                onClick={() => setViewMode('3d')}
              >
                3D Preview
              </button>
              <button
                className={`toggle-btn ${viewMode === 'layers' ? 'active' : ''}`}
                onClick={() => setViewMode('layers')}
              >
                Layer View
              </button>
            </div>
          )}
          {hasSupportMesh && jobId && (
            <a
              href={`${API_BASE}/api/jobs/${jobId}/support.stl`}
              download="support.stl"
              className="download-btn"
            >
              Download Support STL
            </a>
          )}
        </div>
      )}

      {localModelUrl && viewMode === '3d' && (
        <div className="viewer-3d">
          <STLViewer
            key={`${localModelUrl}-${hasSupportMesh}`}
            modelUrl={localModelUrl}
            supportUrl={hasSupportMesh && jobId ? `${API_BASE}/api/jobs/${jobId}/support.stl` : undefined}
            width={600}
            height={450}
          />
          <div className="viewer-legend">
            <span className="legend-item"><span className="color-box model"></span> Model</span>
            {hasSupportMesh && <span className="legend-item"><span className="color-box support"></span> Supports</span>}
          </div>
        </div>
      )}

      <div className="viewer" style={{ display: viewMode === 'layers' ? 'block' : 'none' }}>
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
