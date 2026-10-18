// SPDX-License-Identifier: MIT
// Compatibility entry point; no duplicate input engine or observer.
import { pathToFileURL } from 'node:url';
import { runObserver } from '../../native/obs/live-input.mjs';
export * from '../../native/obs/live-input.mjs';
if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) runObserver();
