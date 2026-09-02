/**
 * Scene 的 React 外殼。
 *
 * 它只做兩件事：掛載 canvas、在卸載時 dispose。
 * 所有渲染邏輯都在 Scene.ts 裡，這個檔案刻意保持很薄。
 */

import { useEffect, useRef } from 'react'
import { Scene } from './Scene'

interface ViewerProps {
  /** Scene 建立完成後回呼一次。App 用它拿到 Scene 實例來操作場景。 */
  onSceneReady: (scene: Scene) => void
  /** Scene 即將銷毀前回呼。 */
  onSceneDispose?: () => void
}

export function Viewer({ onSceneReady, onSceneDispose }: ViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // 用 ref 存回呼，effect 才能只跑一次，不受回呼身份變動影響。
  const readyRef = useRef(onSceneReady)
  const disposeRef = useRef(onSceneDispose)
  readyRef.current = onSceneReady
  disposeRef.current = onSceneDispose

  useEffect(() => {
    if (!containerRef.current)
      return
    const scene = new Scene(containerRef.current)
    readyRef.current(scene)
    return () => {
      disposeRef.current?.()
      scene.dispose()
    }
  }, [])

  return <div ref={containerRef} className="viewer" />
}
