import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

interface STLViewerProps {
  modelUrl: string
  supportUrl?: string
  width?: number
  height?: number
}

export function STLViewer({ modelUrl, supportUrl, width = 400, height = 400 }: STLViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<{
    scene: THREE.Scene
    camera: THREE.PerspectiveCamera
    renderer: THREE.WebGLRenderer
    controls: OrbitControls
    animationId: number
  } | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    // Setup scene
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x1a1a2e)

    // Setup camera
    const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000)
    camera.position.set(50, 50, 50)

    // Setup renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(width, height)
    renderer.setPixelRatio(window.devicePixelRatio)
    containerRef.current.appendChild(renderer.domElement)

    // Setup controls
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.05

    // Add lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5)
    scene.add(ambientLight)

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8)
    directionalLight.position.set(50, 50, 50)
    scene.add(directionalLight)

    const directionalLight2 = new THREE.DirectionalLight(0xffffff, 0.4)
    directionalLight2.position.set(-50, -50, -50)
    scene.add(directionalLight2)

    // Add grid helper on XY plane (Z-up coordinate system)
    const gridHelper = new THREE.GridHelper(100, 10, 0x444444, 0x222222)
    gridHelper.rotation.x = Math.PI / 2  // Rotate to XY plane
    scene.add(gridHelper)

    // Set camera up vector to Z
    camera.up.set(0, 0, 1)

    // Animation loop
    const animate = () => {
      const animationId = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
      if (sceneRef.current) {
        sceneRef.current.animationId = animationId
      }
    }

    sceneRef.current = { scene, camera, renderer, controls, animationId: 0 }
    animate()

    // Cleanup
    return () => {
      if (sceneRef.current) {
        cancelAnimationFrame(sceneRef.current.animationId)
        sceneRef.current.renderer.dispose()
        sceneRef.current.controls.dispose()
      }
      if (containerRef.current) {
        containerRef.current.innerHTML = ''
      }
    }
  }, [width, height])

  // Load models when URLs change
  useEffect(() => {
    if (!sceneRef.current) return

    const { scene, camera } = sceneRef.current
    const loader = new STLLoader()

    // Remove existing meshes (keep lights and grid)
    const meshesToRemove: THREE.Object3D[] = []
    scene.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        meshesToRemove.push(child)
      }
    })
    meshesToRemove.forEach((mesh) => scene.remove(mesh))

    let modelMesh: THREE.Mesh | null = null

    // Load main model
    loader.load(
      modelUrl,
      (geometry) => {
        geometry.computeVertexNormals()
        // Don't center - keep original position

        const material = new THREE.MeshPhongMaterial({
          color: 0x4a90d9,
          specular: 0x111111,
          shininess: 50,
        })
        modelMesh = new THREE.Mesh(geometry, material)
        scene.add(modelMesh)

        // Fit camera to model (Z-up coordinate system)
        const box = new THREE.Box3().setFromObject(modelMesh)
        const center = box.getCenter(new THREE.Vector3())
        const size = box.getSize(new THREE.Vector3())
        const maxDim = Math.max(size.x, size.y, size.z)

        // Position camera looking from front-right-top with Z-up
        camera.position.set(center.x + maxDim, center.y - maxDim, center.z + maxDim * 0.8)
        camera.up.set(0, 0, 1)
        camera.lookAt(center)
        if (sceneRef.current) {
          sceneRef.current.controls.target.copy(center)
        }
      },
      undefined,
      (error) => {
        console.error('Error loading model:', error)
      }
    )

    // Load support mesh if available
    if (supportUrl) {
      loader.load(
        supportUrl,
        (geometry) => {
          geometry.computeVertexNormals()
          // Don't center - keep original position to align with model

          const material = new THREE.MeshPhongMaterial({
            color: 0xe94560,
            specular: 0x111111,
            shininess: 30,
            transparent: true,
            opacity: 0.85,
          })
          const mesh = new THREE.Mesh(geometry, material)
          scene.add(mesh)
        },
        undefined,
        (error) => {
          console.error('Error loading support mesh:', error)
        }
      )
    }
  }, [modelUrl, supportUrl])

  return <div ref={containerRef} className="stl-viewer" />
}
