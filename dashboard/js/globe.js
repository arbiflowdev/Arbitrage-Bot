// Self-contained interactive dotted globe (canvas 2D, no dependencies).
// Auto-rotates, drag to spin, glowing accent markers — the look of the
// v0 "custom globe" templates, rendered offline.

export function createGlobe(canvas, opts = {}) {
  const ctx = canvas.getContext("2d");
  const accent = opts.accent || [56, 189, 248]; // cyan
  const dotRGB = opts.dot || [120, 140, 170];
  const N = opts.points || 1100;
  const markers = opts.markers || [];

  // Evenly distributed points on a unit sphere (fibonacci spiral).
  const pts = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const t = golden * i;
    pts.push([Math.cos(t) * r, y, Math.sin(t) * r]);
  }

  const latLngTo3D = (lat, lng) => {
    const phi = ((90 - lat) * Math.PI) / 180;
    const theta = ((lng + 180) * Math.PI) / 180;
    return [
      -Math.sin(phi) * Math.cos(theta),
      Math.cos(phi),
      Math.sin(phi) * Math.sin(theta),
    ];
  };
  const markerPts = markers.map((m) => latLngTo3D(m.lat, m.lng));

  let a = 0; // rotation around Y
  let tilt = -0.42; // fixed-ish tilt around X
  let dragging = false;
  let lastX = 0;
  let lastY = 0;
  let spin = 0.0016; // auto-rotate speed
  let dpr = 1;
  let cx = 0;
  let cy = 0;
  let R = 120;

  function resize() {
    const rect = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, rect.width * dpr);
    canvas.height = Math.max(1, rect.height * dpr);
    cx = canvas.width / 2;
    cy = canvas.height / 2;
    R = Math.min(canvas.width, canvas.height) * 0.42;
  }
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);

  function project([x, y, z]) {
    // rotate around Y
    const ca = Math.cos(a);
    const sa = Math.sin(a);
    let x1 = x * ca + z * sa;
    let z1 = -x * sa + z * ca;
    const y1 = y;
    // tilt around X
    const ct = Math.cos(tilt);
    const st = Math.sin(tilt);
    const y2 = y1 * ct - z1 * st;
    const z2 = y1 * st + z1 * ct;
    return [cx + x1 * R, cy - y2 * R, z2]; // z2: 1 front .. -1 back
  }

  function frame() {
    if (!canvas.isConnected) {
      ro.disconnect();
      return; // canvas removed (page changed) — stop the loop
    }
    if (!dragging) a += spin;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // soft glow
    const glow = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.25);
    glow.addColorStop(0, `rgba(${accent[0]},${accent[1]},${accent[2]},0.16)`);
    glow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(cx, cy, R * 1.25, 0, Math.PI * 2);
    ctx.fill();

    // globe dots
    for (let i = 0; i < pts.length; i++) {
      const [sx, sy, z] = project(pts[i]);
      const depth = (z + 1) / 2; // 0 back .. 1 front
      if (z < -0.15) continue;
      const alpha = 0.12 + depth * depth * 0.7;
      const size = (0.5 + depth * 1.5) * dpr;
      ctx.fillStyle = `rgba(${dotRGB[0]},${dotRGB[1]},${dotRGB[2]},${alpha})`;
      ctx.beginPath();
      ctx.arc(sx, sy, size, 0, Math.PI * 2);
      ctx.fill();
    }

    // pulsing accent markers
    const pulse = (Math.sin(Date.now() / 600) + 1) / 2;
    for (const mp of markerPts) {
      const [sx, sy, z] = project(mp);
      if (z < 0) continue;
      const depth = (z + 1) / 2;
      const base = (2.2 + depth * 1.5) * dpr;
      ctx.fillStyle = `rgba(${accent[0]},${accent[1]},${accent[2]},${0.85 * depth})`;
      ctx.beginPath();
      ctx.arc(sx, sy, base, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = `rgba(${accent[0]},${accent[1]},${accent[2]},${0.5 * depth * (1 - pulse)})`;
      ctx.lineWidth = 1.5 * dpr;
      ctx.beginPath();
      ctx.arc(sx, sy, base + pulse * 10 * dpr, 0, Math.PI * 2);
      ctx.stroke();
    }

    requestAnimationFrame(frame);
  }

  // drag to spin
  const onDown = (e) => {
    dragging = true;
    const p = e.touches ? e.touches[0] : e;
    lastX = p.clientX;
    lastY = p.clientY;
  };
  const onMove = (e) => {
    if (!dragging) return;
    const p = e.touches ? e.touches[0] : e;
    a += (p.clientX - lastX) * 0.006;
    tilt = Math.max(-1.1, Math.min(1.1, tilt + (p.clientY - lastY) * 0.004));
    lastX = p.clientX;
    lastY = p.clientY;
  };
  const onUp = () => { dragging = false; };
  canvas.addEventListener("mousedown", onDown);
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
  canvas.addEventListener("touchstart", onDown, { passive: true });
  canvas.addEventListener("touchmove", onMove, { passive: true });
  canvas.addEventListener("touchend", onUp);
  canvas.style.cursor = "grab";

  requestAnimationFrame(frame);
}
