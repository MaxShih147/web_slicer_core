/**
 * three.js 場景。純類別，不依賴 React。
 *
 * 這樣切開的理由：這個工具的目的是驗證 slicer core 的修改，
 * 不是驗證 React。three.js 邏輯離開元件生命週期後，
 * 改渲染行為不會被 re-render 干擾。
 *
 * 座標系是 Z-up，和 PrusaSlicer 一致。STL 直接讀，不做任何軸轉換。
 * 模型與支撐共用同一個世界原點，兩者都不做 center，直接疊加就會對齊。
 */

import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'

/** 模型顏色：藍。 */
const MODEL_COLOR = 0x4A90D9
/** 支撐顏色：橘紅。刻意和模型高對比，一眼分得出來。 */
const SUPPORT_COLOR = 0xE94560

const BACKGROUND_COLOR = 0x1A1A2E
const GRID_SIZE = 200
const GRID_DIVISIONS = 20

export class Scene {
  private container: HTMLElement
  private scene: THREE.Scene
  private camera: THREE.PerspectiveCamera
  private renderer: THREE.WebGLRenderer
  private controls: OrbitControls
  private grid: THREE.GridHelper
  private axes: THREE.AxesHelper
  private loader: STLLoader
  private resizeObserver: ResizeObserver
  private animationId = 0

  private modelMesh: THREE.Mesh | null = null
  private supportMesh: THREE.Mesh | null = null
  private disposed = false

  constructor(container: HTMLElement) {
    this.container = container
    this.loader = new STLLoader()

    const width = container.clientWidth || 1
    const height = container.clientHeight || 1

    this.scene = new THREE.Scene()
    this.scene.background = new THREE.Color(BACKGROUND_COLOR)

    this.camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 5000)
    // Z-up。這行必須在 OrbitControls 建立前設定，否則旋轉軸會歪掉。
    this.camera.up.set(0, 0, 1)
    this.camera.position.set(120, -120, 100)

    this.renderer = new THREE.WebGLRenderer({ antialias: true })
    this.renderer.setSize(width, height)
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    container.appendChild(this.renderer.domElement)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.08
    this.controls.target.set(0, 0, 0)

    this.scene.add(new THREE.AmbientLight(0xFFFFFF, 0.55))

    const keyLight = new THREE.DirectionalLight(0xFFFFFF, 0.85)
    keyLight.position.set(80, -80, 120)
    this.scene.add(keyLight)

    const fillLight = new THREE.DirectionalLight(0xFFFFFF, 0.35)
    fillLight.position.set(-80, 80, -60)
    this.scene.add(fillLight)

    // 格線放在 XY 平面（GridHelper 預設躺在 XZ）。
    this.grid = new THREE.GridHelper(GRID_SIZE, GRID_DIVISIONS, 0x555577, 0x2A2A44)
    this.grid.rotation.x = Math.PI / 2
    this.scene.add(this.grid)

    // 原點軸標：紅=X、綠=Y、藍=Z。判斷模型擺放方向用。
    this.axes = new THREE.AxesHelper(30)
    this.scene.add(this.axes)

    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(container)

    this.animate()
  }

  private animate = (): void => {
    if (this.disposed)
      return
    this.animationId = requestAnimationFrame(this.animate)
    this.controls.update()
    this.renderer.render(this.scene, this.camera)
  }

  private resize(): void {
    const width = this.container.clientWidth
    const height = this.container.clientHeight
    if (width === 0 || height === 0)
      return
    this.camera.aspect = width / height
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(width, height)
  }

  private disposeMesh(mesh: THREE.Mesh | null): void {
    if (!mesh)
      return
    this.scene.remove(mesh)
    mesh.geometry.dispose()
    const material = mesh.material
    if (Array.isArray(material))
      material.forEach(item => item.dispose())
    else
      material.dispose()
  }

  private async parseStl(blob: Blob): Promise<THREE.BufferGeometry> {
    const buffer = await blob.arrayBuffer()
    const geometry = this.loader.parse(buffer)
    geometry.computeVertexNormals()
    return geometry
  }

  /** 載入模型。會取代前一個模型，並自動把相機對到模型上。 */
  async setModel(blob: Blob): Promise<void> {
    const geometry = await this.parseStl(blob)
    if (this.disposed) {
      geometry.dispose()
      return
    }
    this.disposeMesh(this.modelMesh)
    const material = new THREE.MeshPhongMaterial({
      color: MODEL_COLOR,
      specular: 0x222222,
      shininess: 40,
      flatShading: false,
    })
    this.modelMesh = new THREE.Mesh(geometry, material)
    this.scene.add(this.modelMesh)
    this.frameAll()
  }

  /**
   * 載入支撐 mesh。傳 null 代表清掉支撐。
   * 不做 center，因為支撐和模型共用世界原點。
   */
  async setSupport(blob: Blob | null): Promise<void> {
    if (blob === null) {
      this.disposeMesh(this.supportMesh)
      this.supportMesh = null
      return
    }
    const geometry = await this.parseStl(blob)
    if (this.disposed) {
      geometry.dispose()
      return
    }
    this.disposeMesh(this.supportMesh)
    const material = new THREE.MeshPhongMaterial({
      color: SUPPORT_COLOR,
      specular: 0x111111,
      shininess: 25,
      transparent: true,
      opacity: 0.9,
    })
    this.supportMesh = new THREE.Mesh(geometry, material)
    this.scene.add(this.supportMesh)
  }

  /** 清掉模型與支撐。 */
  clearAll(): void {
    this.disposeMesh(this.modelMesh)
    this.disposeMesh(this.supportMesh)
    this.modelMesh = null
    this.supportMesh = null
  }

  /** 相機對焦到目前所有 mesh 的整體範圍。沒有 mesh 時回到預設視角。 */
  frameAll(): void {
    const box = new THREE.Box3()
    if (this.modelMesh)
      box.expandByObject(this.modelMesh)
    if (this.supportMesh)
      box.expandByObject(this.supportMesh)

    if (box.isEmpty()) {
      this.camera.position.set(120, -120, 100)
      this.controls.target.set(0, 0, 0)
      this.controls.update()
      return
    }

    const center = box.getCenter(new THREE.Vector3())
    const size = box.getSize(new THREE.Vector3())
    const maxDim = Math.max(size.x, size.y, size.z, 1)

    // 從右前上方看，符合 Z-up 的直覺視角。
    this.camera.position.set(
      center.x + maxDim * 1.2,
      center.y - maxDim * 1.2,
      center.z + maxDim * 0.9,
    )
    this.camera.near = maxDim / 100
    this.camera.far = maxDim * 100
    this.camera.updateProjectionMatrix()
    this.controls.target.copy(center)
    this.controls.update()
  }

  /** 切換模型顯示。方便單獨檢查支撐結構。 */
  setModelVisible(visible: boolean): void {
    if (this.modelMesh)
      this.modelMesh.visible = visible
  }

  /** 切換支撐顯示。 */
  setSupportVisible(visible: boolean): void {
    if (this.supportMesh)
      this.supportMesh.visible = visible
  }

  /** 切換模型線框。看支撐穿進模型多深時用得到。 */
  setModelWireframe(wireframe: boolean): void {
    if (this.modelMesh)
      (this.modelMesh.material as THREE.MeshPhongMaterial).wireframe = wireframe
  }

  setGridVisible(visible: boolean): void {
    this.grid.visible = visible
    this.axes.visible = visible
  }

  dispose(): void {
    this.disposed = true
    cancelAnimationFrame(this.animationId)
    this.resizeObserver.disconnect()
    this.clearAll()
    this.grid.geometry.dispose()
    ;(this.grid.material as THREE.Material).dispose()
    this.axes.geometry.dispose()
    ;(this.axes.material as THREE.Material).dispose()
    this.controls.dispose()
    this.renderer.dispose()
    if (this.renderer.domElement.parentNode)
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement)
  }
}
