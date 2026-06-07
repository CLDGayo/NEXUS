import { useMemo, useRef, useState, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { prefersReducedMotion } from '../../lib/gsap';

// Frosted-pastel liquid background: slow-drifting 3D spheres (glassdeform.jpg).
// The frost/refraction is provided by the UI's backdrop-filter glass panels
// sitting OVER this canvas — here we only paint glossy drifting orbs.
//
// Perf guardrails: dpr capped, frameloop pauses when the tab is hidden, and
// motion is frozen to a single static frame under prefers-reduced-motion.
// Mounted lazily (see AppShell) so three.js never blocks first paint.

// glassdeform palette — slate-blue + bold pastels that read against the cream
// app base (pale orbs vanish on cream, so these are saturated a notch).
const ORBS = [
  { pos: [-3.0, 1.5, 0], scale: 1.8, color: '#6f86b8', speed: 0.5, phase: 0.0 },
  { pos: [2.8, 0.7, -1], scale: 2.1, color: '#7d8ff0', speed: 0.38, phase: 1.2 },
  { pos: [-1.6, -1.8, 0.5], scale: 1.35, color: '#8fd6b6', speed: 0.62, phase: 2.4 },
  { pos: [2.2, -2.0, -0.5], scale: 1.55, color: '#f0aec1', speed: 0.46, phase: 3.1 },
  { pos: [0.3, 2.4, -1.5], scale: 1.25, color: '#9cc2ec', speed: 0.54, phase: 4.0 },
  { pos: [3.6, 2.2, -2], scale: 1.0, color: '#d8c49c', speed: 0.7, phase: 5.2 },
];

function Orb({ pos, scale, color, speed, phase, animate }) {
  const ref = useRef();
  const base = useMemo(() => pos, [pos]);

  useFrame((state) => {
    if (!animate || !ref.current) return;
    const t = state.clock.elapsedTime * speed + phase;
    // gentle bob + sway — keeps orbs slowly morphing through the frame.
    ref.current.position.x = base[0] + Math.sin(t * 0.7) * 0.45;
    ref.current.position.y = base[1] + Math.cos(t) * 0.4;
    ref.current.position.z = base[2] + Math.sin(t * 0.5) * 0.3;
    ref.current.rotation.y = t * 0.15;
  });

  return (
    <mesh ref={ref} position={pos} scale={scale}>
      <sphereGeometry args={[1, 48, 48]} />
      <meshPhysicalMaterial
        color={color}
        roughness={0.22}
        metalness={0.1}
        clearcoat={1}
        clearcoatRoughness={0.25}
        sheen={0.6}
        sheenColor="#ffffff"
      />
    </mesh>
  );
}

function Scene({ animate }) {
  return (
    <>
      <ambientLight intensity={0.85} />
      <directionalLight position={[5, 6, 5]} intensity={1.6} color="#fff6e8" />
      <directionalLight position={[-6, -2, 3]} intensity={0.7} color="#cfe0f5" />
      <pointLight position={[0, -4, 4]} intensity={0.6} color="#f0d2db" />
      {ORBS.map((o, i) => (
        <Orb key={i} {...o} animate={animate} />
      ))}
    </>
  );
}

export default function LiquidBackground() {
  const reduced = prefersReducedMotion();
  // Pause the render loop when the tab is hidden (battery / GPU friendly).
  const [hidden, setHidden] = useState(
    typeof document !== 'undefined' && document.hidden,
  );

  useEffect(() => {
    const onVis = () => setHidden(document.hidden);
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  const animate = !reduced && !hidden;

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 z-0"
      style={{ filter: 'blur(80px) saturate(150%)', willChange: 'filter' }}
    >
      <Canvas
        dpr={[1, 1.5]}
        frameloop={animate ? 'always' : 'demand'}
        camera={{ position: [0, 0, 6], fov: 52 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
        style={{ background: 'transparent' }}
      >
        <Scene animate={animate} />
      </Canvas>
    </div>
  );
}
