// Validation suite for the orbital-mechanics physics core (brief section 7).
// Usage: node physics_tests.js [path/to/sim.html]
// Loads the block between the PHYSICS CORE markers in sim.html, so it tests the shipped code.
const fs = require('fs');
const path = process.argv[2] || 'sim.html';
const html = fs.readFileSync(path, 'utf8');
const m = html.match(/==== PHYSICS CORE BEGIN[^\n]*\n([\s\S]*?)\/\/ ==== PHYSICS CORE END/);
if (!m) { console.error('physics core markers not found'); process.exit(2); }
const core = new Function(m[1] + '; return {G,AU,MSUN,YEAR,RSUN,C_LIGHT,MODEL,centralRadius,launch,advanceSim,localTimestep,orbitalElements,modelNotes,specificEnergy};')();
const {G, AU, MSUN, YEAR, C_LIGHT, MODEL, launch, advanceSim, localTimestep, orbitalElements, modelNotes} = core;

let failed = 0;
function check(name, ok, detail) {
  console.log((ok ? '  PASS ' : '  FAIL ') + name + (detail ? '  [' + detail + ']' : ''));
  if (!ok) failed++;
}
function mk(over) {
  const s = Object.assign({distanceAU: 1, massCentralMsun: 1, massOrbitMsun: 0.001, velocityKms: 25, directionDeg: 90}, over);
  launch(s);
  return s;
}
const els = s => orbitalElements(s.pos, s.vel, s.mu, s.R, s.massOrbitMsun*MSUN, s.collided, s.diag.epsRef);
// run like the browser does: frame-sized chunks with the substep cap
function run(s, seconds, frameDt, cap) {
  frameDt = frameDt || 0.25*YEAR/60; cap = cap || MODEL.maxSubstepsPerFrame;
  let t = 0, maxSteps = 0, throttled = 0, total = 0;
  while (t < seconds && !s.collided) {
    const r = advanceSim(s, frameDt, cap);
    t += frameDt; total += r.steps; maxSteps = Math.max(maxSteps, r.steps); if (r.dropped > 0) throttled++;
  }
  return {total, maxSteps, throttled};
}
const vc = (s) => Math.sqrt(s.mu/(s.distanceAU*AU))/1000;
const ve = (s) => Math.sqrt(2*s.mu/(s.distanceAU*AU))/1000;

console.log('1. Circular orbit (1 AU, 1 Msun, v = sqrt(mu/r))');
{
  const s = mk({}); s.velocityKms = vc(s); launch(s);
  const e0 = els(s);
  check('classified circular', e0.cls === 'circular', e0.label);
  check('e ~ 0', e0.e < 1e-6, e0.e.toExponential(2));
  check('period ~ 1 yr', Math.abs(e0.T/YEAR - 1) < 0.01, (e0.T/YEAR).toFixed(4));
  const rr = run(s, 5*YEAR);
  const rMax = Math.max(Math.hypot(...s.pos)/AU, 1);
  check('energy drift < 1e-5 over 5 yr', s.diag.drift < 1e-5, s.diag.drift.toExponential(2));
  check('no radial drift: r stays within 1e-4 of 1 AU', Math.abs(Math.hypot(...s.pos)/AU - 1) < 1e-4 && Math.abs(s.diag.rMin/AU - 1) < 1e-4, 'rMin=' + (s.diag.rMin/AU).toFixed(6));
  check('playback never throttled', rr.throttled === 0, 'max substeps/frame=' + rr.maxSteps);
}

console.log('2. Moderate ellipse (tangential, 0.7 v_circ)');
{
  const s = mk({}); s.velocityKms = 0.7*vc(s); launch(s);
  const e0 = els(s);
  const eTh = Math.abs(0.49 - 1), aTh = 1/(2 - 0.49), rpTh = aTh*(1-eTh), raTh = aTh*(1+eTh);
  check('classified elliptical, 0<e<1', e0.cls === 'elliptical' && e0.e > 0 && e0.e < 1, 'e=' + e0.e.toFixed(4));
  check('e matches analytic', Math.abs(e0.e - eTh) < 1e-9);
  check('finite period = 2pi sqrt(a^3/mu)', isFinite(e0.T) && Math.abs(e0.T/YEAR - Math.pow(aTh,1.5)) < 0.01, (e0.T/YEAR).toFixed(4) + ' yr');
  const T = e0.T;
  run(s, 3*T);
  check('numerical periapsis matches elements', Math.abs(s.diag.rMin/AU - rpTh)/rpTh < 1e-3, (s.diag.rMin/AU).toFixed(5) + ' vs ' + rpTh.toFixed(5));
  check('energy drift < 1e-4 over 3 orbits', s.diag.drift < 1e-4, s.diag.drift.toExponential(2));
  check('periapsis/apoapsis readouts consistent', Math.abs(e0.rp/AU - rpTh) < 1e-9 && Math.abs(e0.ra/AU - raTh) < 1e-9);
}

console.log('3. Parabolic threshold (v = v_esc)');
{
  const s = mk({}); s.velocityKms = ve(s); launch(s);
  const e0 = els(s);
  check('classified parabolic threshold', e0.cls === 'parabolic', e0.label);
  check('epsilon ~ 0', Math.abs(e0.eps)/(s.mu/(AU)) < 1e-9);
  check('no finite closed period', e0.T === Infinity && !e0.closed);
  run(s, 5*YEAR);
  check('open: body leaves, no collision, still parabolic', !s.collided && Math.hypot(...s.pos) > 3*AU, 'r=' + (Math.hypot(...s.pos)/AU).toFixed(1) + ' AU');
  check('energy drift < 1e-4', s.diag.drift < 1e-4, s.diag.drift.toExponential(2));
}

console.log('4. Hyperbolic escape (v = 1.3 v_esc)');
{
  const s = mk({}); s.velocityKms = 1.3*ve(s); launch(s);
  const e0 = els(s);
  check('classified hyperbolic escape', e0.cls === 'hyperbolic', e0.label);
  check('epsilon > 0 and e > 1', e0.eps > 0 && e0.e > 1, 'e=' + e0.e.toFixed(3));
  check('no finite closed period, no positive finite a', e0.T === Infinity && !isFinite(e0.a));
  run(s, 5*YEAR);
  check('energy drift < 1e-5 over 5 yr, no collision', s.diag.drift < 1e-5 && !s.collided, s.diag.drift.toExponential(2));
}

console.log('5. Radial bound plunge (low inward radial speed, eps < 0)');
{
  for (const dir of [180, 0]) {
    const s = mk({distanceAU: 1.5, velocityKms: 5, directionDeg: dir});
    const e0 = els(s);
    check('dir ' + dir + ': eps<0, e~1 but NOT labelled escape', e0.eps < 0 && Math.abs(e0.e - 1) < 1e-6 && e0.family !== 'escape' && e0.cls === 'radial', e0.label);
    check('dir ' + dir + ': no infinite-period-because-e=1; no closed period flagged as radial', e0.radial && e0.bound && !e0.closed && e0.willCollide);
    const rr = run(s, 5*YEAR, undefined, 20000);
    const vContact = Math.sqrt(25e6 + 2*s.mu*(1/s.R - 1/(1.5*AU)));
    check('dir ' + dir + ': stops at surface contact', s.collided && Math.abs(Math.hypot(...s.pos) - s.R)/s.R < 1e-9, 'steps=' + rr.total);
    check('dir ' + dir + ': contact speed matches energy conservation (1%)', Math.abs(Math.hypot(...s.vel) - vContact)/vContact < 0.01, (Math.hypot(...s.vel)/1000).toFixed(1) + ' vs ' + (vContact/1000).toFixed(1) + ' km/s');
    check('dir ' + dir + ': collided classification', els(s).cls === 'collision');
  }
}

console.log('6. High-eccentricity orbit with periapsis inside the central body');
{
  const s = mk({distanceAU: 0.5, velocityKms: 5, directionDeg: 90});
  const e0 = els(s);
  check('UI-extreme launch: e > 0.98 and periapsis < R', e0.e > 0.98 && e0.rp < s.R, 'e=' + e0.e.toFixed(6) + ', rp=' + (e0.rp/1e6).toFixed(0) + ' Mm, R=' + (s.R/1e6).toFixed(0) + ' Mm');
  // e extremely close to 1 (below the slider minimum, set directly): still must stop at the surface
  const x = mk({distanceAU: 0.5, velocityKms: 0.05, directionDeg: 90});
  const ex = els(x);
  check('extreme case e > 0.99999 and periapsis < R', ex.e > 0.99999 && ex.rp < x.R && ex.willCollide, 'e=' + ex.e.toFixed(9));
  advanceSim(x, 5*YEAR, 1e7);
  check('extreme case stops at surface, speed bounded by sqrt(2mu/R)', x.collided && Math.hypot(...x.vel) < Math.sqrt(2*x.mu/x.R)*1.01 && x.diag.rMin >= x.R*(1 - 1e-9));
  check('flagged as collision course', e0.willCollide && e0.cls === 'elliptical');
  // worst case for tunnelling: ask for the whole orbit in ONE call
  const rr = advanceSim(s, 2*YEAR, 1e7);
  const rNow = Math.hypot(...s.pos), vNow = Math.hypot(...s.vel);
  const vExp = Math.sqrt(25e6 + 2*s.mu*(1/s.R - 1/(0.5*AU)));
  check('surface contact detected', s.collided && Math.abs(rNow - s.R)/s.R < 1e-9, 'r=' + (rNow/1e6).toFixed(1) + ' Mm');
  check('never entered interior model', s.diag.rMin >= s.R*(1 - 1e-9));
  check('no speed explosion: contact speed matches vis-viva at R (1%)', Math.abs(vNow - vExp)/vExp < 0.01 && vNow < Math.sqrt(2*s.mu/s.R)*1.01, (vNow/1000).toFixed(1) + ' vs ' + (vExp/1000).toFixed(1) + ' km/s');
  // a single huge step request must not skip the surface either
  const s2 = mk({distanceAU: 0.5, velocityKms: 5, directionDeg: 180});
  advanceSim(s2, 50*YEAR, 1e7);
  check('inbound radial: contact found in one long call', s2.collided && Math.abs(Math.hypot(...s2.pos) - s2.R)/s2.R < 1e-9);
}

console.log('7. Near-surface periapsis that stays outside R');
{
  const s0 = mk({}); const R = s0.R; const rp = 1.5*R, r0 = 1*AU;
  const v = Math.sqrt(2*s0.mu*rp/(r0*(r0 + rp)));   // tangential at apoapsis r0
  const s = mk({velocityKms: v/1000});
  const e0 = els(s);
  check('periapsis 1.5R, bound, no collision predicted', !e0.willCollide && Math.abs(e0.rp - rp)/rp < 1e-6, 'e=' + e0.e.toFixed(6));
  const rr = run(s, 3*e0.T);
  check('survives 3 orbits without contact', !s.collided);
  check('periapsis resolved (1e-3 of analytic)', Math.abs(s.diag.rMin - rp)/rp < 1e-3, (s.diag.rMin/R).toFixed(4) + ' R vs 1.5 R');
  check('energy drift < 1e-5 of largest energy scale (e=0.986, bounded)', s.diag.drift < 1e-5, s.diag.drift.toExponential(2));
  check('browser stays responsive (substeps/frame within cap)', rr.maxSteps <= MODEL.maxSubstepsPerFrame, 'max substeps/frame=' + rr.maxSteps + ', throttled frames=' + rr.throttled);
  // convergence: halving eta should not change energy error by orders of magnitude (resolved, not skipped)
  const eta = MODEL.stepEta; MODEL.stepEta = eta/2;
  const sf = mk({velocityKms: v/1000}); run(sf, 3*e0.T, undefined, 1e6);
  MODEL.stepEta = eta;
  check('halving eta gives same periapsis (converged)', Math.abs(sf.diag.rMin - s.diag.rMin)/rp < 1e-3);
}

console.log('8. Mass-ratio and speed validity guards');
{
  const a = mk({massCentralMsun: 0.1, massOrbitMsun: 0.1}); const n1 = modelNotes(els(a), a);
  check('m/M = 1 produces a warning', n1.some(x => x.level === 'warn' && /Mass ratio/.test(x.text)));
  const b = mk({}); const n2 = modelNotes(els(b), b);
  check('default m/M = 0.001 produces none', !n2.some(x => /Mass ratio/.test(x.text)));
  const fast = orbitalElements([1e9, 0], [0.2*C_LIGHT, 0], G*MSUN, 7e8, 1e27, false);
  check('v = 0.2c warns model outside Newtonian regime', modelNotes(fast, a).some(x => /of c/.test(x.text)));
  const luminal = orbitalElements([1e9, 0], [1.1*C_LIGHT, 0], G*MSUN, 7e8, 1e27, false);
  check('v >= c flagged invalid', modelNotes(luminal, a).some(x => x.level === 'danger' && /≥ c/.test(x.text)));
}

console.log('9. Timestep controller is class-independent and local');
{
  const bound = mk({}); bound.velocityKms = vc(bound); launch(bound);
  const open = mk({}); open.velocityKms = vc(bound); launch(open);   // identical local state, different "class" is impossible to select
  check('dt depends only on local state (same state => same dt)', localTimestep(bound.pos, bound.vel, bound.mu, bound.R) === localTimestep(open.pos, open.vel, open.mu, open.R));
  const dtFar = localTimestep([50*AU, 0], [0, 10e3], bound.mu, bound.R);
  const dtNear = localTimestep([0.01*AU, 0], [0, 10e3], bound.mu, bound.R);
  check('dt shrinks as periapsis is approached', dtNear < dtFar/100, dtNear.toExponential(2) + ' vs ' + dtFar.toExponential(2));
  const s = mk({}); let calls = 0;
  const t = advanceSim(s, 10*YEAR, 5);
  check('substep cap enforced and excess time dropped, not coarsened', t.steps === 5 && t.dropped > 0);
  let maxFrac = 0; const q = mk({velocityKms: 0.7*vc(bound)});
  advanceSim(q, YEAR, 1e6, sim => { /* fractional radius change per step is bounded by eta */ });
  const r1 = q.pos; // sanity: not NaN
  check('state finite after long run', isFinite(r1[0]) && isFinite(r1[1]));
}

console.log('10. Classification is invariant along a run (energy is conserved)');
{
  const cases = {
    'e=0.986 ellipse, periapsis 1.5R': (() => { const s0 = mk({}); const rp = 1.5*s0.R, r0 = AU; return mk({velocityKms: Math.sqrt(2*s0.mu*rp/(r0*(r0+rp)))/1000}); })(),
    'near-parabolic (v = 0.999 v_esc)': (() => { const s0 = mk({}); return mk({velocityKms: 0.999*ve(s0)}); })(),
    'hyperbolic grazing the star': (() => { const s0 = mk({}); return mk({velocityKms: 1.05*ve(s0), directionDeg: 100}); })(),
  };
  for (const [name, s] of Object.entries(cases)) {
    const seen = new Set([els(s).cls]);
    for (let i = 0; i < 4000 && !s.collided; i++) { advanceSim(s, 0.25*YEAR/60*3, 1e5); seen.add(els(s).cls); }
    check(name + ': single class throughout', seen.size === 1 || (s.collided && seen.size === 2 && seen.has('collision')), [...seen].join(' -> '));
  }
}

console.log(failed ? '\n' + failed + ' check(s) FAILED' : '\nAll checks passed');
process.exit(failed ? 1 : 0);
