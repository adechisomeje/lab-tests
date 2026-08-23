#!/usr/bin/env node
/**
 * Zero-dependency read-only API over the lab-tests dataset.
 *
 *   node api/server.js            # http://localhost:3000
 *   PORT=8080 node api/server.js
 *
 * Everything is loaded into memory once at boot and served from there; the
 * dataset is a few megabytes and never changes at runtime.
 */
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (p) => JSON.parse(readFileSync(join(ROOT, p), 'utf8'));

const { meta, tests } = read('data/tests.json');
const categories = read('data/categories.json').categories;
const profiles = read('data/clinic-profiles.json').profiles;
const departments = read('data/departments.json').departments;
const specimens = read('data/specimens.json').specimens;

const byId = new Map(tests.map((t) => [t.id, t]));

/** Fold a string for accent- and case-insensitive search. */
const fold = (s) =>
  (s ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();

// Precomputed haystack so search does not re-fold on every request.
const haystack = new Map(
  tests.map((t) => [t.id, fold([t.name, ...(t.aliases ?? []), t.description ?? ''].join(' '))])
);

function filter(query) {
  const { q, department, category, clinic, specimen, core, min_completeness } = query;
  const needle = q ? fold(q) : null;
  const wantCore = core === 'true' || core === '1';

  return tests.filter((t) => {
    if (needle && !haystack.get(t.id).includes(needle)) return false;
    if (department && fold(t.department) !== fold(department)) return false;
    if (category && !(t.categories ?? []).includes(category)) return false;
    if (specimen && !(t.specimen?.types ?? []).includes(specimen)) return false;
    if (clinic) {
      const hit = (t.clinic_profiles ?? []).find((c) => c.profile === clinic);
      if (!hit) return false;
      if (wantCore && !hit.core) return false;
    }
    if (min_completeness && (t.completeness?.score ?? 0) < Number(min_completeness)) return false;
    return true;
  });
}

function paginate(rows, query) {
  const limit = Math.min(Number(query.limit) || 50, 500);
  const offset = Number(query.offset) || 0;
  return { total: rows.length, limit, offset, results: rows.slice(offset, offset + limit) };
}

const ROUTES = [
  [/^\/$/, () => ({
    name: meta.name,
    version: meta.version,
    test_count: meta.test_count,
    disclaimer: meta.disclaimer,
    endpoints: {
      '/tests': 'list & filter (q, department, category, clinic, core, specimen, min_completeness, limit, offset)',
      '/tests/:id': 'single test record',
      '/categories': 'clinical categories',
      '/categories/:id': 'category with its tests',
      '/clinics': 'clinic-type profiles',
      '/clinics/:id': 'profile with its tests (?core=true for the curated core panel)',
      '/departments': 'performing departments',
      '/specimens': 'specimen types',
    },
  })],
  [/^\/tests$/, (_m, query) => paginate(filter(query), query)],
  [/^\/tests\/([^/]+)$/, (m) => byId.get(decodeURIComponent(m[1])) ?? null],
  [/^\/categories$/, () => ({ categories: categories.map(({ test_ids, ...c }) => c) })],
  [/^\/categories\/([^/]+)$/, (m, query) => {
    const c = categories.find((x) => x.id === m[1]);
    if (!c) return null;
    return { ...c, test_ids: undefined, ...paginate(c.test_ids.map((i) => byId.get(i)), query) };
  }],
  [/^\/clinics$/, () => ({ profiles: profiles.map(({ test_ids, core_test_ids, ...p }) => p) })],
  [/^\/clinics\/([^/]+)$/, (m, query) => {
    const p = profiles.find((x) => x.id === m[1]);
    if (!p) return null;
    const wantCore = query.core === 'true' || query.core === '1';
    const ids = wantCore ? p.core_test_ids : p.test_ids;
    const { test_ids, core_test_ids, ...rest } = p;
    return { ...rest, ...paginate(ids.map((i) => byId.get(i)), query) };
  }],
  [/^\/departments$/, () => ({ departments: departments.map(({ test_ids, ...d }) => d) })],
  [/^\/specimens$/, () => ({ specimens: specimens.map(({ test_ids, ...s }) => s) })],
];

const server = createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname.replace(/\/+$/, '') || '/';
  const query = Object.fromEntries(url.searchParams);

  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'public, max-age=3600');

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405);
    return res.end(JSON.stringify({ error: 'method not allowed' }));
  }

  for (const [pattern, handler] of ROUTES) {
    const m = path.match(pattern);
    if (!m) continue;
    let body;
    try {
      body = handler(m, query);
    } catch (err) {
      res.writeHead(500);
      return res.end(JSON.stringify({ error: 'internal error', detail: String(err.message) }));
    }
    if (body === null) {
      res.writeHead(404);
      return res.end(JSON.stringify({ error: 'not found', path }));
    }
    res.writeHead(200);
    return res.end(JSON.stringify(body, null, 2));
  }

  res.writeHead(404);
  res.end(JSON.stringify({ error: 'not found', path, hint: 'GET / for the endpoint list' }));
});

const port = Number(process.env.PORT) || 3000;
server.listen(port, () => {
  console.log(`lab-tests api on http://localhost:${port} (${tests.length} tests)`);
});
