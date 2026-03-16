import { useEffect, useRef } from 'react'
import * as THREE from 'three'

export function useWebGraph() {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(window.innerWidth, window.innerHeight)

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(
      50, window.innerWidth / window.innerHeight, 0.1, 200
    )
    camera.position.set(0, 12, 22)
    camera.lookAt(0, 0, 0)

    // ── Colors ──
    const COL_ACCENT = new THREE.Color(0xF54E00)
    const COL_SECONDARY = new THREE.Color(0xF7A501)
    const COL_DIM = new THREE.Color(0x332820)
    const COL_GLOW = new THREE.Color(0xFF6B2C)

    // ── Generate web graph nodes ──
    const NODE_COUNT = 40
    const nodes = []
    const SPREAD = 16

    for (let i = 0; i < NODE_COUNT; i++) {
      const angle = (i / NODE_COUNT) * Math.PI * 2 + Math.random() * 0.5
      const radius = 2 + Math.random() * (SPREAD - 2)
      const x = Math.cos(angle) * radius * (0.6 + Math.random() * 0.4)
      const z = Math.sin(angle) * radius * (0.6 + Math.random() * 0.4)
      const y = (Math.random() - 0.5) * 6
      const size = 0.12 + Math.random() * 0.18
      const importance = Math.max(0, 1 - radius / SPREAD) + Math.random() * 0.3
      nodes.push({ pos: new THREE.Vector3(x, y, z), size, importance, phase: Math.random() * Math.PI * 2 })
    }

    // Central hub node
    nodes.push({ pos: new THREE.Vector3(0, 0, 0), size: 0.3, importance: 1.0, phase: 0 })

    // ── Build edges - connect nearby nodes ──
    const edges = []
    const MAX_EDGE_DIST = 8
    for (let i = 0; i < nodes.length; i++) {
      const connections = []
      for (let j = i + 1; j < nodes.length; j++) {
        const d = nodes[i].pos.distanceTo(nodes[j].pos)
        if (d < MAX_EDGE_DIST) {
          connections.push({ j, d })
        }
      }
      connections.sort((a, b) => a.d - b.d)
      const maxConn = i === nodes.length - 1 ? 8 : 3
      for (let k = 0; k < Math.min(maxConn, connections.length); k++) {
        edges.push([i, connections[k].j])
      }
    }

    // ── Node spheres ──
    const nodeGeo = new THREE.SphereGeometry(1, 16, 16)
    const nodeMat = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uAccent: { value: COL_ACCENT },
        uGlow: { value: COL_GLOW },
      },
      vertexShader: `
        varying vec3 vNorm;
        varying vec3 vWorldPos;
        void main() {
          vNorm = normalize(normalMatrix * normal);
          vWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        varying vec3 vNorm;
        varying vec3 vWorldPos;
        uniform float uTime;
        uniform vec3 uAccent;
        uniform vec3 uGlow;

        void main() {
          vec3 n = normalize(vNorm);
          vec3 viewDir = normalize(cameraPosition - vWorldPos);
          float fresnel = pow(1.0 - max(dot(n, viewDir), 0.0), 3.0);

          vec3 light = normalize(vec3(0.5, 1.0, 0.3));
          float diff = max(dot(n, light), 0.0) * 0.6;
          float spec = pow(max(dot(reflect(-light, n), viewDir), 0.0), 32.0) * 0.4;

          vec3 base = mix(uAccent * 0.6, uGlow, fresnel * 0.5);
          vec3 color = base * (0.2 + diff) + vec3(1.0, 0.85, 0.7) * spec;
          color += uGlow * fresnel * 0.3;

          gl_FragColor = vec4(color, 0.9);
        }
      `,
      transparent: true,
    })

    const nodeMeshes = []
    for (const node of nodes) {
      const mesh = new THREE.Mesh(nodeGeo, nodeMat)
      mesh.position.copy(node.pos)
      mesh.scale.setScalar(node.size)
      scene.add(mesh)
      nodeMeshes.push(mesh)
    }

    // ── Edge lines ──
    const edgePositions = []
    for (const [a, b] of edges) {
      edgePositions.push(nodes[a].pos.x, nodes[a].pos.y, nodes[a].pos.z)
      edgePositions.push(nodes[b].pos.x, nodes[b].pos.y, nodes[b].pos.z)
    }

    const edgeGeo = new THREE.BufferGeometry()
    edgeGeo.setAttribute('position', new THREE.Float32BufferAttribute(edgePositions, 3))

    const edgeMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 } },
      transparent: true,
      depthWrite: false,
      vertexShader: `
        varying float vDist;
        void main() {
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vDist = -mv.z;
          gl_Position = projectionMatrix * mv;
        }
      `,
      fragmentShader: `
        uniform float uTime;
        varying float vDist;
        void main() {
          float fog = smoothstep(60.0, 15.0, vDist);
          gl_FragColor = vec4(0.95, 0.4, 0.1, fog * 0.12);
        }
      `,
    })
    const edgeMesh = new THREE.LineSegments(edgeGeo, edgeMat)
    scene.add(edgeMesh)

    // ── Crawler ball - travels along edges ──
    const crawlerGeo = new THREE.SphereGeometry(0.25, 32, 32)
    const crawlerMat = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uCamPos: { value: new THREE.Vector3() },
      },
      vertexShader: `
        varying vec3 vNorm;
        varying vec3 vWorldPos;
        void main() {
          vNorm = normalize(normalMatrix * normal);
          vWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        varying vec3 vNorm;
        varying vec3 vWorldPos;
        uniform float uTime;
        uniform vec3 uCamPos;

        void main() {
          vec3 n = normalize(vNorm);
          vec3 viewDir = normalize(uCamPos - vWorldPos);
          float fresnel = pow(1.0 - max(dot(n, viewDir), 0.0), 3.0);

          vec3 light1 = normalize(vec3(0.5, 1.0, 0.3));
          float spec1 = pow(max(dot(reflect(-light1, n), viewDir), 0.0), 60.0);

          vec3 base = vec3(1.0, 0.35, 0.0);
          vec3 hot = vec3(1.0, 0.7, 0.2);
          vec3 color = mix(base, hot, fresnel * 0.8 + 0.2);
          color += vec3(1.0, 0.95, 0.85) * spec1 * 1.5;
          color += hot * fresnel * 0.4;

          gl_FragColor = vec4(color, 1.0);
        }
      `,
    })
    const crawler = new THREE.Mesh(crawlerGeo, crawlerMat)
    crawler.renderOrder = 10
    scene.add(crawler)

    // ── Build crawler path through graph ──
    const crawlPath = []
    const visited = new Set()
    let current = nodes.length - 1 // start at hub
    for (let step = 0; step < 200; step++) {
      crawlPath.push(nodes[current].pos.clone())
      visited.add(current)
      const neighbors = edges
        .filter(([a, b]) => a === current || b === current)
        .map(([a, b]) => (a === current ? b : a))
      if (neighbors.length === 0) break
      const unvisited = neighbors.filter((n) => !visited.has(n))
      if (unvisited.length > 0) {
        current = unvisited[Math.floor(Math.random() * unvisited.length)]
      } else {
        current = neighbors[Math.floor(Math.random() * neighbors.length)]
        visited.clear()
      }
    }
    const crawlCurve = new THREE.CatmullRomCurve3(crawlPath, true, 'centripetal', 0.3)
    const crawlPoints = crawlCurve.getPoints(crawlPath.length * 8)

    // ── Trail ──
    const TRAIL_MAX = 80
    const trailHistory = []
    let trailMesh = null

    function buildTrail() {
      if (trailHistory.length < 4) return null
      const tc = new THREE.CatmullRomCurve3(trailHistory, false, 'centripetal', 0.5)
      const tGeo = new THREE.TubeGeometry(tc, trailHistory.length * 2, 0.03, 6, false)
      const count = tGeo.attributes.position.count
      const alphas = new Float32Array(count)
      for (let i = 0; i < count; i++) alphas[i] = i / count
      tGeo.setAttribute('alpha', new THREE.BufferAttribute(alphas, 1))

      const tMat = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        vertexShader: `
          attribute float alpha;
          varying float vAlpha;
          void main() {
            vAlpha = alpha;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `,
        fragmentShader: `
          varying float vAlpha;
          void main() {
            float a = pow(vAlpha, 2.5) * 0.4;
            vec3 col = mix(vec3(0.2, 0.08, 0.02), vec3(0.95, 0.4, 0.05), vAlpha);
            gl_FragColor = vec4(col, a);
          }
        `,
      })
      return new THREE.Mesh(tGeo, tMat)
    }

    // ── Ambient particles ──
    const PARTICLE_COUNT = 120
    const pPos = new Float32Array(PARTICLE_COUNT * 3)
    const pSizes = new Float32Array(PARTICLE_COUNT)
    const pPhases = new Float32Array(PARTICLE_COUNT)

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      pPos[i * 3] = (Math.random() - 0.5) * 30
      pPos[i * 3 + 1] = (Math.random() - 0.5) * 12
      pPos[i * 3 + 2] = (Math.random() - 0.5) * 30
      pSizes[i] = 0.3 + Math.random() * 0.8
      pPhases[i] = Math.random() * Math.PI * 2
    }

    const pGeo = new THREE.BufferGeometry()
    pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3))
    pGeo.setAttribute('size', new THREE.BufferAttribute(pSizes, 1))

    const pMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 } },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      vertexShader: `
        attribute float size;
        varying float vDist;
        void main() {
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vDist = -mv.z;
          gl_PointSize = size * (60.0 / vDist);
          gl_Position = projectionMatrix * mv;
        }
      `,
      fragmentShader: `
        uniform float uTime;
        varying float vDist;
        void main() {
          float d = length(gl_PointCoord - 0.5);
          if (d > 0.5) discard;
          float a = smoothstep(0.5, 0.1, d);
          float fog = smoothstep(50.0, 10.0, vDist);
          float flicker = 0.5 + 0.5 * sin(uTime * 2.0 + vDist * 0.5);
          gl_FragColor = vec4(0.95, 0.45, 0.1, a * fog * flicker * 0.06);
        }
      `,
    })
    scene.add(new THREE.Points(pGeo, pMat))

    // ── Data pulse particles traveling along edges ──
    const PULSE_COUNT = 30
    const pulses = []
    for (let i = 0; i < PULSE_COUNT; i++) {
      const edgeIdx = Math.floor(Math.random() * edges.length)
      const [a, b] = edges[edgeIdx]
      const pulseMesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.05, 8, 8),
        new THREE.MeshBasicMaterial({ color: COL_SECONDARY, transparent: true, opacity: 0.6 })
      )
      scene.add(pulseMesh)
      pulses.push({
        mesh: pulseMesh,
        from: nodes[a].pos,
        to: nodes[b].pos,
        t: Math.random(),
        speed: 0.2 + Math.random() * 0.4,
        edgeIdx,
      })
    }

    // ── Mouse ──
    let mouseX = 0, mouseY = 0
    const onMove = (e) => {
      mouseX = (e.clientX / window.innerWidth - 0.5) * 2
      mouseY = (e.clientY / window.innerHeight - 0.5) * 2
    }
    window.addEventListener('mousemove', onMove)

    // Pause animation when canvas is off-screen
    let isVisible = true
    const visObserver = new IntersectionObserver(
      ([entry]) => { isVisible = entry.isIntersecting },
      { threshold: 0 }
    )
    visObserver.observe(canvas)

    const lookTarget = new THREE.Vector3(0, 0, 0)
    const clock = new THREE.Clock()
    let raf
    let frameCount = 0

    function loop() {
      raf = requestAnimationFrame(loop)
      if (!isVisible) return
      const t = clock.getElapsedTime()
      const dt = clock.getDelta()
      frameCount++

      // Update uniforms
      nodeMat.uniforms.uTime.value = t
      edgeMat.uniforms.uTime.value = t
      crawlerMat.uniforms.uTime.value = t
      crawlerMat.uniforms.uCamPos.value.copy(camera.position)
      pMat.uniforms.uTime.value = t

      // Camera - gentle orbit + mouse
      const camAngle = t * 0.04
      const tx = Math.sin(camAngle) * 2.5 + mouseX * 1.5
      const tz = 22 + Math.cos(camAngle * 0.7) * 2 + mouseY * 1.0
      const ty = 12 + Math.sin(t * 0.08) * 0.5
      camera.position.x += (tx - camera.position.x) * 0.01
      camera.position.z += (tz - camera.position.z) * 0.01
      camera.position.y += (ty - camera.position.y) * 0.01

      // Crawler along path
      const totalPts = crawlPoints.length
      const rawT = (t * 0.025) % 1
      const pathIdx = rawT * totalPts
      const i0 = Math.floor(pathIdx) % totalPts
      const i1 = (i0 + 1) % totalPts
      const frac = pathIdx - Math.floor(pathIdx)
      const cp = crawlPoints[i0].clone().lerp(crawlPoints[i1], frac)
      crawler.position.copy(cp)

      // LookAt tracks crawler loosely
      const idealLook = new THREE.Vector3(cp.x * 0.3, cp.y * 0.2, cp.z * 0.3)
      lookTarget.lerp(idealLook, 0.015)
      camera.lookAt(lookTarget)

      // Node gentle bob
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i]
        nodeMeshes[i].position.y = n.pos.y + Math.sin(t * 0.8 + n.phase) * 0.15
      }

      // Pulse particles along edges
      for (const p of pulses) {
        p.t += p.speed * 0.008
        if (p.t > 1) {
          p.t = 0
          const edgeIdx = Math.floor(Math.random() * edges.length)
          const [a, b] = edges[edgeIdx]
          p.from = nodes[a].pos
          p.to = nodes[b].pos
        }
        p.mesh.position.lerpVectors(p.from, p.to, p.t)
        p.mesh.material.opacity = Math.sin(p.t * Math.PI) * 0.6
      }

      // Ambient particles drift
      const pp = pGeo.attributes.position.array
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        pp[i * 3 + 1] += Math.sin(t * 0.5 + pPhases[i]) * 0.001
        pp[i * 3] += Math.cos(t * 0.3 + pPhases[i]) * 0.0006
      }
      pGeo.attributes.position.needsUpdate = true

      // Trail
      trailHistory.push(cp.clone())
      if (trailHistory.length > TRAIL_MAX) trailHistory.shift()

      if (frameCount % 4 === 0 && trailHistory.length >= 4) {
        if (trailMesh) {
          scene.remove(trailMesh)
          trailMesh.geometry.dispose()
          trailMesh.material.dispose()
        }
        trailMesh = buildTrail()
        if (trailMesh) scene.add(trailMesh)
      }

      renderer.render(scene, camera)
    }
    loop()

    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight
      camera.updateProjectionMatrix()
      renderer.setSize(window.innerWidth, window.innerHeight)
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(raf)
      visObserver.disconnect()
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('resize', onResize)
      if (trailMesh) { trailMesh.geometry.dispose(); trailMesh.material.dispose() }
      nodeGeo.dispose(); nodeMat.dispose()
      edgeGeo.dispose(); edgeMat.dispose()
      crawlerGeo.dispose(); crawlerMat.dispose()
      pGeo.dispose(); pMat.dispose()
      for (const p of pulses) { p.mesh.geometry.dispose(); p.mesh.material.dispose() }
      renderer.dispose()
    }
  }, [])

  return canvasRef
}
