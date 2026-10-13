// DataOS in-page helpers for the zero-pass review and batch building.
// Paste into the browser console (or a javascript tool) on any data-os.turing.com page while logged in.
// They drive the normal UI in hidden iframes; they never read tokens or call private APIs.
// Keep concurrency at 3 or fewer; one download at a time.

// Task page -> {id, ds (dataset id), st (READY/ARCHIVED/...), nm (name line)}
window.taskInfo = (id) => new Promise(res => { const f = document.createElement('iframe'); f.style.cssText = 'position:fixed;left:-3000px;top:0;width:1300px;height:1200px'; f.src = '/tasks/' + id; document.body.appendChild(f); const t0 = Date.now(); const tick = () => { let d; try { d = f.contentDocument } catch (e) {} const a = d && [...d.querySelectorAll('a[href*="/datasets/"]')].map(x => x.getAttribute('href')).find(h => /\/datasets\/\d+/.test(h)); const txt = d && d.body ? d.body.innerText.replace(/\s+/g, ' ') : ''; if (a && /(READY|ARCHIVED|DRAFT|PROCESSING|ERROR)/.test(txt)) { const st = (txt.match(/\b(READY|ARCHIVED|DRAFT|PROCESSING|ERROR)\b/) || [])[1]; const nm = (d.querySelector('h1,h2') || {}).innerText || ''; f.remove(); res({id, ds: a.match(/\/datasets\/(\d+)/)[1], st, nm}); } else if (Date.now() - t0 > 30000) { f.remove(); res({id, ds: null, st: 'timeout'}); } else setTimeout(tick, 500); }; setTimeout(tick, 2000); });

// Task page Test Results Matrix -> Headroomness label and the list of tests at 0% in every agent run.
// A task with runs but no matrix returns 'unknown (no per-test results in DataOS)'.
window.headroom = (id) => new Promise(res => { const f = document.createElement('iframe'); f.style.cssText = 'position:fixed;left:-3000px;top:0;width:1400px;height:1400px'; f.src = '/tasks/' + id; document.body.appendChild(f); const t0 = Date.now(); const tick = () => { let t = ''; try { t = f.contentDocument.body.innerText } catch (e) {} const i = t.indexOf('Test Results Matrix'), j = t.indexOf('Legend:'); const ev = (t.match(/Evaluations \((\d+)\)/) || [])[1]; if (i >= 0 && j > i) { const seg = t.slice(i, j); const rates = [...seg.matchAll(/^([^\t\n]+)\t\s*(\d+(?:\.\d+)?)%/gm)].filter(m => !/^TEST/.test(m[1])).map(m => [m[1].trim(), +m[2]]); f.remove(); const z = rates.filter(r => r[1] === 0).map(r => r[0]); const v = !rates.length ? 'unknown (no per-test results in DataOS)' : z.length ? 'yes (some fail)' : rates.every(r => r[1] === 100) ? 'no (100% pass)' : 'Almost 100% pass'; res({id, v, n: rates.length, zero: z, ev}); } else if ((ev === '0' && Date.now() - t0 > 10000) || Date.now() - t0 > 60000) { f.remove(); res({id, v: ev === '0' ? 'no runs yet' : 'unknown (no per-test results in DataOS)', n: 0, zero: [], ev}); } else setTimeout(tick, 700) }; setTimeout(tick, 2500) });

// Your role on a dataset, read from its Share dialog. No Share button means viewer; "Dataset not found" means no access.
// Do NOT infer access from the /datasets list: it omits datasets you can open.
window.myRole = (ds) => new Promise(res => { const f = document.createElement('iframe'); f.style.cssText = 'position:fixed;left:-3000px;top:0;width:1300px;height:1200px'; f.src = '/datasets/' + ds; document.body.appendChild(f); const t0 = Date.now(); let clicked = false; const tick = () => { let d; try { d = f.contentDocument } catch (e) {}; const t = d && d.body ? d.body.innerText.replace(/\s+/g, ' ') : ''; if (/not found/.test(t) && Date.now() - t0 > 6000) { f.remove(); return res({ds, r: 'NOT FOUND'}); } if (!clicked) { const b = d && [...d.querySelectorAll('button')].find(b => b.innerText.trim() === 'Share'); if (b) { b.click(); clicked = true; } } else { const m = t.match(/Khiem Doan (ADMIN|OPERATOR|VIEWER)/); if (m) { f.remove(); return res({ds, r: m[1]}); } } if (Date.now() - t0 > 30000) { f.remove(); return res({ds, r: clicked ? 'no own entry' : 'no Share button (viewer)'}); } setTimeout(tick, 700) }; setTimeout(tick, 3000) });

// Download "Task with runs" for one task (file lands in ~/Downloads as <uuid>.tmp; mover_all.py stages it).
// Run a sequential queue with a gap; parallel downloads have crashed the session before.
window.dlOne = (id, holdMs = 75000) => new Promise(res => { const f = document.createElement('iframe'); f.style.cssText = 'position:fixed;left:-3000px;top:0;width:1300px;height:1400px'; f.src = '/tasks/' + id; document.body.appendChild(f); const t0 = Date.now(); let clicked = false; const tick = () => { let d; try { d = f.contentDocument } catch (e) {} const B = d ? [...d.querySelectorAll('button')] : []; if (!clicked) { const b = B.find(x => (x.getAttribute('aria-label') || '').includes('Download this task') || x.innerText.trim() === 'Download'); if (b) { b.click(); clicked = true; } } else { const m = B.find(x => x.innerText && x.innerText.trim() === 'Task with runs'); if (m) { m.click(); setTimeout(() => { f.remove(); res({id, ok: 1}); }, holdMs); return; } } if (Date.now() - t0 > 60000) { f.remove(); return res({id, ok: 0, clicked}); } setTimeout(tick, 700); }; setTimeout(tick, 2000); });
window.dlQueue = async (ids) => { window.__dl = {}; for (const id of ids) window.__dl[id] = await window.dlOne(id); window.__dldone = true; };

// Copy tasks I (ids) from source dataset DS into target dataset targetName (targetId) via "Copy tasks".
// The returned "started" flag is not proof; confirm the target's Tasks (N) count and names afterwards.
window.copyInto2 = async (DS, I, targetName, targetId) => {
  const S = m => new Promise(r => setTimeout(r, m));
  const f = document.createElement('iframe'); f.style.cssText = 'position:fixed;left:-3000px;top:0;width:1300px;height:1600px'; f.src = '/datasets/' + DS; document.body.appendChild(f);
  const W = () => f.contentWindow, D = () => f.contentDocument;
  const U = async (fn, m = 15e3) => { const t = Date.now(); while (Date.now() - t < m) { let v; try { v = fn(); } catch (e) {} if (v) return v; await S(200); } return null; };
  const V = (e, v) => { const p = e.tagName == 'SELECT' ? W().HTMLSelectElement.prototype : W().HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(p, 'value').set.call(e, v); e.dispatchEvent(new (W().Event)(e.tagName == 'SELECT' ? 'change' : 'input', {bubbles: true})); };
  const B = re => [...D().querySelectorAll('button')].find(b => re.test(b.innerText.trim()));
  const F = 'input[placeholder^="Filter by ids"]';
  const all = () => I.every(i => D().querySelector(`a[href="/tasks/${i}"]`));
  const done = (r) => { f.remove(); return r; };
  try {
    if (!await U(() => B(/^Tasks \(\d+\)$/), 25e3)) return done({d: DS, err: 'no Tasks'});
    await S(5000);
    if (!D().querySelector(F)) { B(/^Tasks \(\d+\)$/).click(); await U(() => D().querySelector(F), 6000); }
    let how = 'as shown';
    if (!await U(all, 4000)) { const ib = D().querySelector(F); if (ib) { V(ib, I.join(', ')); how = 'id filter'; } }
    if (!await U(all, 8000)) { const st = [...D().querySelectorAll('select')].find(s => [...s.options].some(o => o.value == 'READY')); if (st) { V(st, ''); how += '+all statuses'; } }
    if (!await U(all, 12000)) return done({d: DS, err: 'not listed', how});
    await S(600);
    const rid = c => { let e = c; for (let k = 0; k < 8 && e; k++) { e = e.parentElement; const a = e?.querySelectorAll('a[href^="/tasks/"]'); if (a && a.length) return a.length == 1 && e.querySelectorAll('input[type=checkbox]').length == 1 ? a[0].getAttribute('href').slice(7) : null; } return null; };
    let h = 0; for (const c of D().querySelectorAll('input[type=checkbox]')) { const id = rid(c); if (id && I.includes(id)) { if (!c.checked) c.click(); h++; } }
    if (h !== I.length) return done({d: DS, err: 'ticked ' + h});
    const cb = await U(() => B(new RegExp(`^Copy tasks \\(${I.length}\\)$`))); if (!cb) return done({d: DS, err: 'no copy btn'}); cb.click();
    const se = await U(() => D().querySelector('input[placeholder^="Search datasets by name"]')); V(se, targetName);
    const re = new RegExp('^' + targetName + ' \\(' + targetId + '\\)');
    const op = await U(() => [...D().querySelectorAll('button,li,[role=option],div')].reverse().find(e => re.test((e.innerText || '').trim()) && e.children.length < 3)); if (!op) return done({d: DS, err: 'no target'}); op.click();
    const cf = await U(() => { const b = B(new RegExp(`^Copy ${I.length} tasks?$`)); return b && !b.disabled ? b : null; }); if (!cf) return done({d: DS, err: 'no confirm'});
    cf.click(); const s2 = await U(() => B(/^Copying tasks/), 8000); await S(1500);
    return done({d: DS, ok: 1, n: I.length, how, started: !!s2});
  } catch (e) { return done({d: DS, err: String(e)}); }
};
