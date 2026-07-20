#!/usr/bin/env node
/**
 * Upsert this extension's entry in a checked-out copy of the
 * serverkit-extensions registry (index.json). Run by the release workflow
 * after the GitHub release exists — the sha256 is computed from the
 * PUBLISHED asset (downloaded from the release), never from a local build,
 * so the registry always matches what the panel downloads.
 *
 * Usage:
 *   node scripts/update-registry.mjs --zip dist/<name>-<version>.zip \
 *        --tag vX.Y.Z --registry ../serverkit-extensions
 *
 * Env:
 *   GITHUB_REPOSITORY  owner/name of this repo (used for source/repo URLs)
 */
import { createHash } from 'crypto';
import { promises as fs } from 'fs';
import path from 'path';

function arg(flag) {
    const i = process.argv.indexOf(flag);
    return i !== -1 ? process.argv[i + 1] : null;
}

const zipPath = arg('--zip');
const tag = arg('--tag');
const registryDir = arg('--registry') || process.env.REGISTRY_PATH;
if (!zipPath || !tag || !registryDir) {
    console.error('Usage: node scripts/update-registry.mjs --zip <path> --tag <tag> --registry <dir>');
    process.exit(1);
}

const manifest = JSON.parse(await fs.readFile('plugin.json', 'utf8'));
const slug = manifest.name;
const zipName = path.basename(zipPath);
const ghRepo = process.env.GITHUB_REPOSITORY || `jhd3197/${slug}`;
const repoUrl = `https://github.com/${ghRepo}`;

const sha256 = createHash('sha256').update(await fs.readFile(zipPath)).digest('hex');

const indexPath = path.join(registryDir, 'index.json');
const index = JSON.parse(await fs.readFile(indexPath, 'utf8'));
const list = index.extensions || [];

const entry = {
    slug,
    display_name: manifest.display_name,
    description: manifest.description,
    version: tag.replace(/^v/, ''),
    category: manifest.category || 'utility',
    author: manifest.author || '',
    first_party: true,
    bundled: false,
    permissions: manifest.permissions || [],
    min_panel_version: manifest.min_panel_version || null,
    max_panel_version: null,
    source: `${repoUrl}/releases/download/${tag}/${zipName}`,
    sha256,
    repo: repoUrl,
    homepage: manifest.homepage || repoUrl,
    featured: !!manifest.featured,
    feature_score: manifest.feature_score || 0,
};

const i = list.findIndex((e) => e && e.slug === slug);
if (i === -1) {
    list.push(entry);
    console.log(`Added new registry entry for ${slug}`);
} else {
    list[i] = entry;
    console.log(`Updated registry entry for ${slug}`);
}
index.updated = new Date().toISOString().slice(0, 10);

await fs.writeFile(indexPath, JSON.stringify(index, null, 2) + '\n');
console.log(`${slug} ${entry.version} sha256:${sha256}`);
