#!/usr/bin/env node
// Post-build gate for the runtime ESM bundle (frontend/dist/index.mjs).
//
// The panel imports this file straight from a Blob URL inside the browser.
// Nothing Node-flavoured survives there: no `process`, no `require`, no
// `module.exports`, no `__dirname`. Vite's library mode deliberately leaves
// `process.env.NODE_ENV` in place for a downstream bundler to resolve, and a
// bundled dependency (recharts -> react-is / prop-types / tiny-invariant)
// referencing it is enough to break the whole extension at import time with
// "Can't find variable: process". Unit tests never catch that because Node
// has `process`. This check fails the build instead.
//
// Also verifies the bundle only imports the specifiers the panel's import map
// actually provides -- any other bare import would fail to resolve at load.
//
// Usage: node scripts/check-bundle.mjs [path/to/index.mjs]

import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const bundlePath = resolve(process.argv[2] || resolve(here, '..', 'frontend', 'dist', 'index.mjs'));

// Keep in sync with the panel's vendor import map (frontend/src/plugins/runtime/vendorManifest.js).
const HOST_PROVIDED = new Set([
    'react', 'react-dom', 'react-dom/client', 'react/jsx-runtime',
    'react-router-dom', 'i18next', 'react-i18next', 'serverkit-sdk',
]);

const FORBIDDEN = [
    { re: /\bprocess\.env\b/g, why: 'process.env reference (add define: { "process.env.NODE_ENV": ... } to vite.config)' },
    { re: /\bprocess\.(?:browser|platform|version|argv|cwd)\b/g, why: 'Node process API' },
    // A bare `require("x")` call. `obj.require("x")` is a guarded feature
    // probe (e.g. `i && i.require && i.require("util")`) and is fine.
    { re: /(?<![.\w$])require\(\s*["']/g, why: 'CommonJS require()' },
    { re: /\bmodule\.exports\b/g, why: 'CommonJS module.exports' },
    { re: /\b__dirname\b|\b__filename\b/g, why: 'Node path globals' },
    { re: /\bglobal\.(?:process|Buffer)\b/g, why: 'Node global.* reference' },
];

let src;
try {
    src = readFileSync(bundlePath, 'utf8');
} catch (e) {
    console.error(`check-bundle: cannot read ${bundlePath}: ${e.message}`);
    process.exit(2);
}

const problems = [];

// A reference guarded by `typeof process < "u"` / `typeof process !== "undefined"`
// is a runtime feature probe (SDK clients reading an env var when they happen
// to run under Node) and is harmless in the browser.
function isGuarded(index) {
    return /typeof\s+process\s*(?:<|!==?|===?)/.test(src.slice(Math.max(0, index - 120), index));
}

for (const { re, why } of FORBIDDEN) {
    let count = 0;
    for (const m of src.matchAll(re)) {
        if (!isGuarded(m.index)) count += 1;
    }
    if (count) problems.push(`${count}x ${why}`);
}

// Import specifiers. Statement-level matches are anchored to a line start:
// a looser `\bimport` also hits identifiers and string contents inside the
// minified code. The bundle is a single file (inlineDynamicImports), so every
// specifier left is an external the panel must provide.
const specifiers = new Set();
for (const m of src.matchAll(/^import\s+(?:[\w$*{}\s,]+?\s+from\s+)?["']([^"']+)["']/gm)) specifiers.add(m[1]);
for (const m of src.matchAll(/^export\s+(?:\*|\{[^}]*\})\s+from\s+["']([^"']+)["']/gm)) specifiers.add(m[1]);
for (const m of src.matchAll(/\bimport\(\s*["']([^"']+)["']\s*\)/g)) specifiers.add(m[1]);
for (const spec of specifiers) {
    if (spec.startsWith('.') || spec.startsWith('/') || spec.startsWith('blob:') || spec.startsWith('http')) continue;
    if (!HOST_PROVIDED.has(spec)) problems.push(`bare import "${spec}" is not provided by the panel import map`);
}
if (specifiers.size === 0) {
    problems.push('no imports found at all — is this really the built ESM bundle?');
}

if (problems.length) {
    console.error(`check-bundle: ${bundlePath} is not browser-safe:`);
    for (const p of problems) console.error(`  - ${p}`);
    process.exit(1);
}

console.log(`check-bundle: OK ${bundlePath} (${(src.length / 1024).toFixed(0)} KB; externals: ${[...specifiers].join(', ')})`);
