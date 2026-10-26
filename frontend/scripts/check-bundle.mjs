import { readdir, readFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';
import { URL } from 'node:url';
import process from 'node:process';

// Conservative foundation gate: count all emitted JS, including lazy chunks.
const assets = new URL('../dist/assets/', import.meta.url);
const files = (await readdir(assets)).filter(name => name.endsWith('.js'));
if (!files.length) throw new Error('No production JavaScript was emitted.');
const sizes = await Promise.all(files.map(async name => gzipSync(await readFile(new URL(name, assets))).length));
const bytes = sizes.reduce((sum, value) => sum + value, 0);
process.stdout.write(`Foundation JavaScript: ${(bytes / 1024).toFixed(1)} KiB gzip / 350 KiB budget\n`);
if (bytes > 350 * 1024) throw new Error('Foundation JavaScript exceeds the approved bundle budget.');
