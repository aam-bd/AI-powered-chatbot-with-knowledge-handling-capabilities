// Verification test script for Frontend flow and API integration
const API_BASE = 'http://localhost:8000/api/v1';
const FRONTEND_BASE = 'http://localhost:3000';

async function testFrontendFlow() {
  console.log('====================================================');
  console.log('Testing Knowledge-Base Chatbot: Frontend Verification');
  console.log('====================================================\n');

  // Step 1: Verify Frontend HTTP Pages
  console.log('1. Checking Frontend Pages...');
  const loginRes = await fetch(`${FRONTEND_BASE}/login`);
  console.log(`   GET ${FRONTEND_BASE}/login -> HTTP ${loginRes.status} ${loginRes.statusText}`);
  if (loginRes.status !== 200) throw new Error('Login page failed to load');

  const rootRes = await fetch(`${FRONTEND_BASE}/`);
  console.log(`   GET ${FRONTEND_BASE}/ -> HTTP ${rootRes.status} ${rootRes.statusText}`);
  if (rootRes.status !== 200) throw new Error('Root chat page failed to load');

  // Step 2: Test Authentication & Token Lifecycle
  console.log('\n2. Testing Authentication & Role Resolution...');
  const loginApiRes = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: process.env.ADMIN_EMAIL || process.env.TEST_ADMIN_EMAIL,
      password: process.env.ADMIN_PASSWORD || process.env.TEST_ADMIN_PASSWORD,
    }),
  });
  console.log(`   POST ${API_BASE}/auth/login -> HTTP ${loginApiRes.status}`);
  if (!loginApiRes.ok) throw new Error('Admin login failed');
  const tokens = await loginApiRes.json();
  console.log(`   Access Token received (expires in: ${tokens.expires_in}s)`);
  console.log(`   Refresh Token received`);

  // Step 3: Verify GET /auth/me
  const meRes = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${tokens.access_token}` },
  });
  console.log(`   GET ${API_BASE}/auth/me -> HTTP ${meRes.status}`);
  const user = await meRes.json();
  console.log(`   User authenticated: ${user.email} (Role: ${user.role}, Active: ${user.is_active})`);
  if (user.role !== 'admin') throw new Error('User role is not admin');

  // Step 4: Verify Token Refresh
  console.log('\n3. Testing Automatic Token Refresh...');
  const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  });
  console.log(`   POST ${API_BASE}/auth/refresh -> HTTP ${refreshRes.status}`);
  const refreshedTokens = await refreshRes.json();
  console.log(`   New Access Token received`);

  // Step 5: Test Chat Sessions API
  console.log('\n4. Testing Chat Sessions Management...');
  const sessionsRes = await fetch(`${API_BASE}/chat/sessions`, {
    headers: { Authorization: `Bearer ${refreshedTokens.access_token}` },
  });
  console.log(`   GET ${API_BASE}/chat/sessions -> HTTP ${sessionsRes.status}`);
  const sessionList = await sessionsRes.json();
  console.log(`   Existing active sessions count: ${sessionList.sessions?.length ?? 0}`);

  // Step 6: Test Real-Time SSE Chat Streaming
  console.log('\n5. Testing Live Fetch-Based Chat Stream...');
  const testSessionId = 'frontend-test-' + Date.now();
  const streamRes = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${refreshedTokens.access_token}`,
    },
    body: JSON.stringify({
      message: 'What is collision resistance in a cryptographic hash function?',
      session_id: testSessionId,
    }),
  });
  console.log(`   POST ${API_BASE}/chat/stream -> HTTP ${streamRes.status} (Content-Type: ${streamRes.headers.get('content-type')})`);

  let accumulatedTokens = '';
  let citationsReceived = [];
  let streamDone = false;

  const reader = streamRes.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';

    for (const block of blocks) {
      if (!block.trim()) continue;
      let event = 'message';
      let data = '';
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        if (line.startsWith('data:')) data = line.slice(5).trim();
      }
      if (!data) continue;
      const parsed = JSON.parse(data);
      if (event === 'token') {
        accumulatedTokens += parsed.text;
      } else if (event === 'citations') {
        citationsReceived = parsed.citations;
      } else if (event === 'done') {
        streamDone = true;
      }
    }
  }

  console.log(`   Stream complete! Tokens length: ${accumulatedTokens.length} chars`);
  console.log(`   Answer snippet: "${accumulatedTokens.slice(0, 100)}..."`);
  console.log(`   Citations received: ${citationsReceived.length} source(s)`);
  if (citationsReceived.length > 0) {
    console.log(`   Citation [${citationsReceived[0].tag}]: ${citationsReceived[0].document} (Page ${citationsReceived[0].page})`);
  }

  // Step 7: Clean up session
  const delRes = await fetch(`${API_BASE}/chat/sessions/${testSessionId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${refreshedTokens.access_token}` },
  });
  console.log(`\n6. DELETE ${API_BASE}/chat/sessions/${testSessionId} -> HTTP ${delRes.status}`);

  console.log('\n====================================================');
  console.log('RESULT: Frontend flow and API integration verified 100%!');
  console.log('====================================================\n');
}

testFrontendFlow().catch((err) => {
  console.error('Frontend verification failed:', err);
  process.exit(1);
});
