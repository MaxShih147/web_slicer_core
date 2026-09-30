/**
 * dev-interface 主畫面。
 *
 * 左邊是控制面板，右邊是 3D 場景。
 * 工作迴圈：載入 STL → 調參數 → 產生支撐 → 看結果 → 改 slicer core → 重新產生。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AgentError,
  DEFAULT_SUPPORT_CONFIG,
  SUPPORT_NOT_NEEDED,
  generateSupportMesh,
  healthCheck,
} from './api/coreClient'
import type { Stage, SupportConfig, SupportResult } from './api/coreClient'
import { Viewer } from './viewer/Viewer'
import type { Scene } from './viewer/Scene'
import './App.css'

const STAGE_LABEL: Record<Stage, string> = {
  createJob: '建立 job',
  upload: '上傳模型',
  config: '套用參數',
  generate: '觸發支撐產生',
  poll: '等待後端',
  download: '下載支撐 mesh',
  done: '完成',
}

interface ConfigField {
  key: keyof SupportConfig
  label: string
  step: number
  min: number
  max: number
  hint: string
}

const CONFIG_FIELDS: ConfigField[] = [
  { key: 'support_head_front_diameter', label: '接觸點直徑 (mm)', step: 0.05, min: 0.1, max: 2, hint: '支撐頭碰到模型那一端的直徑' },
  { key: 'support_head_penetration', label: '接觸點穿透深度 (mm)', step: 0.05, min: 0, max: 2, hint: '支撐頭埋進模型表面的深度' },
  { key: 'support_pillar_diameter', label: '支柱直徑 (mm)', step: 0.1, min: 0.2, max: 5, hint: '支撐主幹的粗細' },
  { key: 'support_points_density_relative', label: '支撐點密度 (%)', step: 5, min: 0, max: 500, hint: '100 為基準值，越大支撐點越多' },
  { key: 'support_object_elevation', label: '模型抬升高度 (mm)', step: 0.5, min: 0, max: 50, hint: '模型離平台的距離' },
  { key: 'support_critical_angle', label: '臨界角度 (deg)', step: 1, min: 0, max: 90, hint: '超過這個傾角才需要支撐' },
]

export default function App() {
  const sceneRef = useRef<Scene | null>(null)

  const [agentUp, setAgentUp] = useState<boolean | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [config, setConfig] = useState<SupportConfig>({ ...DEFAULT_SUPPORT_CONFIG })
  const [busy, setBusy] = useState(false)
  const [stage, setStage] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SupportResult | null>(null)
  const [supportUrl, setSupportUrl] = useState<string | null>(null)

  const [showModel, setShowModel] = useState(true)
  const [showSupport, setShowSupport] = useState(true)
  const [wireframe, setWireframe] = useState(false)
  const [showGrid, setShowGrid] = useState(true)

  // agent 健康檢查。每 5 秒一次，讓面板上的燈號反映真實狀態。
  useEffect(() => {
    let cancelled = false
    const check = async () => {
      const up = await healthCheck()
      if (!cancelled)
        setAgentUp(up)
    }
    check()
    const timer = setInterval(check, 5000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  // 支撐下載連結。blob 換掉時要收回舊的 object URL，否則記憶體會累積。
  useEffect(() => {
    if (!result?.blob) {
      setSupportUrl(null)
      return
    }
    const url = URL.createObjectURL(result.blob)
    setSupportUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [result])

  const handleSceneReady = useCallback((scene: Scene) => {
    sceneRef.current = scene
  }, [])

  const handleSceneDispose = useCallback(() => {
    sceneRef.current = null
  }, [])

  const handleFileChange = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0] ?? null
    if (!picked)
      return
    setFile(picked)
    setResult(null)
    setError(null)
    setStage('')
    const scene = sceneRef.current
    if (!scene)
      return
    scene.clearAll()
    try {
      await scene.setModel(picked)
    }
    catch (err) {
      setError('STL 解析失敗：' + (err instanceof Error ? err.message : String(err)))
    }
  }, [])

  const handleGenerate = useCallback(async () => {
    if (!file || busy)
      return
    setBusy(true)
    setError(null)
    setResult(null)
    sceneRef.current?.setSupport(null)

    try {
      const generated = await generateSupportMesh({
        file,
        filename: 'model.stl',
        config,
        onStage: (current, detail) => {
          setStage(STAGE_LABEL[current] + (detail ? '（' + detail + '）' : ''))
        },
      })
      setResult(generated)
      if (generated.blob)
        await sceneRef.current?.setSupport(generated.blob)
    }
    catch (err) {
      if (err instanceof AgentError)
        setError('[' + err.code + '] ' + err.message)
      else
        setError(err instanceof Error ? err.message : String(err))
      setStage('')
    }
    finally {
      setBusy(false)
    }
  }, [file, config, busy])

  const updateField = useCallback((key: keyof SupportConfig, raw: string) => {
    const value = Number(raw)
    if (Number.isNaN(value))
      return
    setConfig(prev => ({ ...prev, [key]: value }))
  }, [])

  const resetConfig = useCallback(() => {
    setConfig({ ...DEFAULT_SUPPORT_CONFIG })
  }, [])

  // 顯示開關同步到場景。
  useEffect(() => { sceneRef.current?.setModelVisible(showModel) }, [showModel, result, file])
  useEffect(() => { sceneRef.current?.setSupportVisible(showSupport) }, [showSupport, result])
  useEffect(() => { sceneRef.current?.setModelWireframe(wireframe) }, [wireframe, result, file])
  useEffect(() => { sceneRef.current?.setGridVisible(showGrid) }, [showGrid])

  const notNeeded = result?.outcome === SUPPORT_NOT_NEEDED

  return (
    <div className="app">
      <aside className="panel">
        <header className="panel-header">
          <h1>Dev Interface</h1>
          <span className={'badge ' + (agentUp === null ? 'badge-unknown' : agentUp ? 'badge-up' : 'badge-down')}>
            {agentUp === null ? 'agent 檢查中' : agentUp ? 'agent 連線中' : 'agent 未連線'}
          </span>
        </header>

        {agentUp === false && (
          <p className="hint-error">
            找不到 agent。請先執行 <code>scripts\run_agent.bat</code>。
          </p>
        )}

        <section className="block">
          <h2>1. 模型</h2>
          <label className="file-button">
            選擇 STL 檔案
            <input type="file" accept=".stl" onChange={handleFileChange} />
          </label>
          <p className="filename">{file ? file.name : '尚未選擇檔案'}</p>
        </section>

        <section className="block">
          <div className="block-title">
            <h2>2. 支撐參數</h2>
            <button type="button" className="link-button" onClick={resetConfig}>回預設值</button>
          </div>
          {CONFIG_FIELDS.map(field => (
            <div className="field" key={field.key}>
              <label htmlFor={field.key} title={field.hint}>{field.label}</label>
              <input
                id={field.key}
                type="number"
                step={field.step}
                min={field.min}
                max={field.max}
                value={config[field.key]}
                onChange={event => updateField(field.key, event.target.value)}
              />
            </div>
          ))}
        </section>

        <section className="block">
          <h2>3. 產生</h2>
          <button
            type="button"
            className="primary"
            disabled={!file || busy || agentUp === false}
            onClick={handleGenerate}
          >
            {busy ? '產生中…' : result ? '重新產生支撐' : '產生支撐'}
          </button>
          <p className="hint">
            改完 slicer core 並重啟 agent 之後，直接按這顆。STL 留在記憶體，不用重選檔。
          </p>

          {busy && <p className="status status-busy">{stage}</p>}

          {error && <p className="status status-error">{error}</p>}

          {result && !error && (
            <div className="result">
              {notNeeded
                ? <p className="status status-neutral">後端回報：此模型不需要支撐（SUPPORT_NOT_NEEDED）。</p>
                : <p className="status status-ok">支撐產生完成。</p>}
              <dl>
                <dt>耗時</dt>
                <dd>{result.elapsedMs.toFixed(0)} ms</dd>
                <dt>jobId</dt>
                <dd className="mono">{result.jobId}</dd>
              </dl>
              {supportUrl && (
                <a className="secondary" href={supportUrl} download="support.stl">
                  下載 support.stl
                </a>
              )}
            </div>
          )}
        </section>

        <section className="block">
          <h2>4. 顯示</h2>
          <label className="check">
            <input type="checkbox" checked={showModel} onChange={e => setShowModel(e.target.checked)} />
            顯示模型
          </label>
          <label className="check">
            <input type="checkbox" checked={showSupport} onChange={e => setShowSupport(e.target.checked)} />
            顯示支撐
          </label>
          <label className="check">
            <input type="checkbox" checked={wireframe} onChange={e => setWireframe(e.target.checked)} />
            模型線框
          </label>
          <label className="check">
            <input type="checkbox" checked={showGrid} onChange={e => setShowGrid(e.target.checked)} />
            顯示格線與座標軸
          </label>
          <button type="button" className="secondary" onClick={() => sceneRef.current?.frameAll()}>
            重設視角
          </button>
          <p className="hint">左鍵旋轉．滾輪縮放．右鍵位移</p>
        </section>
      </aside>

      <main className="stage">
        <Viewer onSceneReady={handleSceneReady} onSceneDispose={handleSceneDispose} />
        <div className="legend">
          <span><i className="swatch swatch-model" />模型</span>
          <span><i className="swatch swatch-support" />支撐</span>
        </div>
      </main>
    </div>
  )
}
