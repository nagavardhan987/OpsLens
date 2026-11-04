import test from 'node:test';
import assert from 'node:assert/strict';
import { askOpsLensStream } from './client.js';

test('assistant stream errors reject with a safe retry signal for deterministic endpoint fallback', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(
    'event: error\ndata: {"detail":"private provider stack trace"}\n\n',
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  );
  try {
    await assert.rejects(
      askOpsLensStream({ eventId: 'evt-1', question: 'How can I verify this?' }),
      (error) => {
        assert.equal(error.message.includes('private provider stack trace'), false);
        assert.match(error.message, /retrying with the incident evidence endpoint/);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
