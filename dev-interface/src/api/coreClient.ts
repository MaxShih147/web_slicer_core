/**
 * web_slicer_core agent 客戶端。
 *
 * 流程完全對齊 DS-Online 的 src/services/supportService.js。
 * 所有路徑都是相對路徑，由 Vite proxy 轉發到 https://127.0.0.1:5179。
 */

// ---------------------------------------------------------------------------
// 型別
// ---------------------------------------------------------------------------

/** agent v2 API 的統一回應外殼。 */
export interface V2Response<T = Record<string, unknown>> {
  success: boolean
  message?: string | null
  code?: string
  data?: T | null
}

/** 支撐產生參數。欄位名對應 agent/models.py 的 SLAConfig。 */
export interface SupportConfig {
  support_head_front_diameter: number
  support_head_penetration: number
  support_pillar_diameter: number
  support_points_density_relative: number
  support_object_elevation: number
  support_critical_angle: number
}

export const DEFAULT_SUPPORT_CONFIG: SupportConfig = {
  support_head_front_diameter: 0.4,
  support_head_penetration: 0.2,
  support_pillar_diameter: 1.0,
  support_points_density_relative: 100,
  support_object_elevation: 5.0,
  support_critical_angle: 45.0,
}

export interface JobStatusData {
  jobId: string
  status: string
  supportOutcome?: string | null
  hasSupportMesh?: boolean
  error?: string | null
  progress?: { percent?: number, stage?: string }
}

/** 支撐產生的結果。blob 為 null 代表模型不需要支撐。 */
export interface SupportResult {
  /** 支撐 mesh 的 STL。SUPPORT_NOT_NEEDED 時為 null。 */
  blob: Blob | null
  /** 中性結果標記，目前只有 SUPPORT_NOT_NEEDED。正常成功時為 null。 */
  outcome: string | null
  hasSupportMesh: boolean
  jobId: string
  /** 整段流程耗時，毫秒。 */
  elapsedMs: number
}

/** 流程階段。UI 用它顯示目前進度。 */
export type Stage =
  | 'createJob'
  | 'upload'
  | 'config'
  | 'generate'
  | 'poll'
  | 'download'
  | 'done'

export type StageListener = (stage: Stage, detail?: string) => void

/** agent 回報的失敗。code 來自後端，方便直接比對。 */
export class AgentError extends Error {
  code: string
  constructor(message: string, code = 'AGENT_ERROR') {
    super(message)
    this.name = 'AgentError'
    this.code = code
  }
}

// 後端在模型完全自撐（或只有 pad）時回這個 outcome。
// 這是成功，不是錯誤。此時磁碟上沒有 support.stl，去下載會 404。
export const SUPPORT_NOT_NEEDED = 'SUPPORT_NOT_NEEDED'

const V2 = '/api/v2'

// ---------------------------------------------------------------------------
// 低階呼叫
// ---------------------------------------------------------------------------

async function readV2<T>(response: Response): Promise<V2Response<T>> {
  let payload: V2Response<T>
  try {
    payload = await response.json()
  }
  catch {
    throw new AgentError('agent 回傳非 JSON 內容（HTTP ' + response.status + '）', 'BAD_RESPONSE')
  }
  if (!response.ok) {
    throw new AgentError(
      payload?.message ?? ('HTTP ' + response.status),
      payload?.code ?? ('HTTP_' + response.status),
    )
  }
  return payload
}

/** 健康檢查。用來在 UI 上標示 agent 是否活著。 */
export async function healthCheck(): Promise<boolean> {
  try {
    const response = await fetch('/api/health')
    return response.ok
  }
  catch {
    return false
  }
}

/** 建立新的 slice job，回傳 jobId。 */
export async function createJob(): Promise<string> {
  const response = await fetch(V2 + '/slices', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  const payload = await readV2<{ jobId: string }>(response)
  const jobId = payload.data?.jobId
  if (!payload.success || !jobId)
    throw new AgentError(payload.message ?? '建立 job 失敗', payload.code ?? 'CREATE_JOB_FAILED')
  return jobId
}

/** 上傳模型 STL。後端只收副檔名為 .stl 的檔案。 */
export async function uploadModel(jobId: string, file: Blob, filename = 'model.stl'): Promise<void> {
  const formData = new FormData()
  formData.append('file', file, filename)
  const response = await fetch(V2 + '/slices/' + jobId + '/upload', {
    method: 'POST',
    body: formData,
  })
  const payload = await readV2(response)
  if (!payload.success)
    throw new AgentError(payload.message ?? '上傳模型失敗', payload.code ?? 'UPLOAD_FAILED')
}

/** 更新 job 設定。isAppend=true 代表只覆蓋有給的欄位。 */
export async function updateConfig(
  jobId: string,
  config: Record<string, unknown>,
  isAppend = true,
): Promise<void> {
  const response = await fetch(V2 + '/slices/' + jobId + '/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config, isAppend }),
  })
  const payload = await readV2(response)
  if (!payload.success)
    throw new AgentError(payload.message ?? '更新設定失敗', payload.code ?? 'CONFIG_FAILED')
}

/** 觸發支撐產生。這是非同步的，後端立刻回應，實際工作在背景跑。 */
export async function generateSupports(jobId: string): Promise<void> {
  const response = await fetch(V2 + '/slices/' + jobId + '/generate-supports', { method: 'POST' })
  const payload = await readV2(response)
  if (!payload.success)
    throw new AgentError(payload.message ?? '觸發支撐產生失敗', payload.code ?? 'GENERATE_FAILED')
}

/** 查詢 job 狀態。 */
export async function getJobStatus(jobId: string): Promise<V2Response<JobStatusData>> {
  const response = await fetch(V2 + '/slices/' + jobId)
  return readV2<JobStatusData>(response)
}

export interface PollOptions {
  /** 輪詢間隔，毫秒。預設 100。支撐產生通常一秒內完成。 */
  interval?: number
  /** 總逾時，毫秒。預設 120000。 */
  timeout?: number
  onProgress?: (data: JobStatusData) => void
}

/** 輪詢直到 completed。failed 或逾時則丟出 AgentError。 */
export async function pollUntilComplete(
  jobId: string,
  options: PollOptions = {},
): Promise<JobStatusData> {
  const { interval = 100, timeout = 120000, onProgress } = options
  const startedAt = Date.now()

  for (;;) {
    const payload = await getJobStatus(jobId)

    // 後端在 job 失敗時回 HTTP 200 但 success=false。
    // 這樣輪詢端才分得出「還在跑」和「失敗了」。
    if (!payload.success)
      throw new AgentError(payload.message ?? '支撐產生失敗', payload.code ?? 'JOB_FAILED')

    const data = payload.data
    if (data) {
      onProgress?.(data)
      if (data.status === 'completed')
        return data
      if (data.status === 'failed')
        throw new AgentError(data.error ?? '支撐產生失敗', 'JOB_FAILED')
    }

    if (Date.now() - startedAt > timeout)
      throw new AgentError('輪詢逾時（' + timeout + 'ms）', 'JOB_TIMEOUT')

    await new Promise(resolve => setTimeout(resolve, interval))
  }
}

/** 下載支撐 mesh。只在 job completed 且 hasSupportMesh 為 true 時呼叫。 */
export async function getSupportStl(jobId: string): Promise<Blob> {
  const response = await fetch('/api/jobs/' + jobId + '/support.stl')
  if (!response.ok)
    throw new AgentError('下載 support.stl 失敗（HTTP ' + response.status + '）', 'DOWNLOAD_FAILED')
  return response.blob()
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

/**
 * 跑完整段支撐產生流程。
 *
 * 每次呼叫都建立全新的 job，不重用 jobId。
 * 重用會讀到磁碟上的舊 support.stl，改過的參數會被無聲忽略。
 * 這是 DS-Online 踩過的坑，見 supportService.js 的 ensureSupportJob 註解。
 */
export async function generateSupportMesh(params: {
  file: Blob
  filename?: string
  config: SupportConfig
  onStage?: StageListener
}): Promise<SupportResult> {
  const { file, filename = 'model.stl', config, onStage } = params
  const startedAt = performance.now()

  onStage?.('createJob')
  const jobId = await createJob()

  onStage?.('upload')
  await uploadModel(jobId, file, filename)

  onStage?.('config')
  await updateConfig(jobId, { supports_enable: true, ...config }, true)

  onStage?.('generate')
  await generateSupports(jobId)

  onStage?.('poll')
  const status = await pollUntilComplete(jobId, {
    onProgress: (data) => {
      const percent = data.progress?.percent
      onStage?.('poll', percent === undefined ? data.status : data.status + ' ' + percent + '%')
    },
  })

  const outcome = status.supportOutcome ?? null
  const hasSupportMesh = status.hasSupportMesh ?? false

  // 中性結果：模型自撐或只有 pad，沒有支撐柱。
  // 此時沒有 support.stl 可下載。硬去抓會 404 並被誤判成產生失敗。
  if (outcome === SUPPORT_NOT_NEEDED && !hasSupportMesh) {
    onStage?.('done')
    return {
      blob: null,
      outcome,
      hasSupportMesh: false,
      jobId,
      elapsedMs: performance.now() - startedAt,
    }
  }

  onStage?.('download')
  const blob = await getSupportStl(jobId)

  onStage?.('done')
  return {
    blob,
    outcome: null,
    hasSupportMesh: true,
    jobId,
    elapsedMs: performance.now() - startedAt,
  }
}
