import test from 'node:test';
import assert from 'node:assert/strict';
import { getHandoverHistory } from './client.js';

test('handover history returns saved records from the API response contract', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ count: 1, handovers: [{ handover_id: 'handover-1' }] }), { status: 200 });
  try {
    assert.deepEqual(await getHandoverHistory(), [{ handover_id: 'handover-1' }]);
  } finally { globalThis.fetch = previousFetch; }
});

test('handover history preserves HTTP status and backend detail for diagnosis', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Database is temporarily locked.' }), { status: 503, statusText: 'Service Unavailable' });
  try {
    await assert.rejects(getHandoverHistory(), /HTTP 503\): Database is temporarily locked/);
  } finally { globalThis.fetch = previousFetch; }
});

test('handover history rejects a malformed response instead of showing a false empty state', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ count: 2 }), { status: 200 });
  try {
    await assert.rejects(getHandoverHistory(), /did not contain a handovers list/);
  } finally { globalThis.fetch = previousFetch; }
});

test('handover history explains when the backend cannot be reached', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  try {
    await assert.rejects(getHandoverHistory(), /Could not reach OpsLens API.*VITE_API_BASE_URL/);
  } finally { globalThis.fetch = previousFetch; }
});
