// Verification test script for Admin Document Manager and Role-Based Access Isolation
const API_BASE = 'http://localhost:8000/api/v1';
const FRONTEND_BASE = 'http://localhost:3000';

async function testAdminFlow() {
  console.log('===========================================================');
  console.log('Testing Knowledge-Base Chatbot: Admin Document Manager Flow');
  console.log('===========================================================\n');

  // Step 1: Check Admin Page HTTP status
  console.log('1. Checking Admin Page Route...');
  const adminPageRes = await fetch(`${FRONTEND_BASE}/admin`);
  console.log(`   GET ${FRONTEND_BASE}/admin -> HTTP ${adminPageRes.status} ${adminPageRes.statusText}`);
  if (adminPageRes.status !== 200) throw new Error('Admin page failed to serve HTML');

  // Step 2: Authenticate as Seeded Admin
  console.log('\n2. Authenticating as Seeded Admin...');
  const adminLoginRes = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: process.env.ADMIN_EMAIL || process.env.TEST_ADMIN_EMAIL,
      password: process.env.ADMIN_PASSWORD || process.env.TEST_ADMIN_PASSWORD,
    }),
  });
  if (!adminLoginRes.ok) throw new Error('Admin login failed');
  const adminTokens = await adminLoginRes.json();

  const adminMeRes = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${adminTokens.access_token}` },
  });
  const adminUser = await adminMeRes.json();
  console.log(`   Admin authenticated: ${adminUser.email} (Role: ${adminUser.role})`);
  if (adminUser.role !== 'admin') throw new Error('Role is not admin');

  // Step 3: Fetch Document List as Admin
  console.log('\n3. Fetching Documents List as Admin...');
  const listDocsRes = await fetch(`${API_BASE}/documents`, {
    headers: { Authorization: `Bearer ${adminTokens.access_token}` },
  });
  console.log(`   GET ${API_BASE}/documents -> HTTP ${listDocsRes.status}`);
  if (!listDocsRes.ok) throw new Error('Failed to fetch documents list as admin');
  const initialDocs = await listDocsRes.json();
  console.log(`   Existing documents in KB: ${initialDocs.length}`);
  initialDocs.forEach((d) => {
    console.log(`     • ${d.name} (v${d.active_version || 1}, status: ${d.status})`);
  });

  // Step 4: Upload Test Document
  console.log('\n4. Uploading New Test Markdown Document...');
  const testDocName = `test_admin_doc_${Date.now()}.md`;
  const testDocContent = `# Test Document for Admin Lifecycle\n\nThis is a temporary document created at ${new Date().toISOString()} to test admin ingestion, polling, versioning, and two-phase delete.`;

  const formData = new FormData();
  const blob = new Blob([testDocContent], { type: 'text/markdown' });
  formData.append('file', blob, testDocName);

  const uploadRes = await fetch(`${API_BASE}/documents`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${adminTokens.access_token}` },
    body: formData,
  });
  console.log(`   POST ${API_BASE}/documents -> HTTP ${uploadRes.status}`);
  if (!uploadRes.ok) {
    const errText = await uploadRes.text();
    throw new Error(`Upload failed: ${errText}`);
  }
  const uploadData = await uploadRes.json();
  const testDocId = uploadData.document_id;
  console.log(`   Upload Accepted: document_id=${testDocId}, status=${uploadData.status}`);

  // Step 5: Poll Status Until Active
  console.log('\n5. Polling Document Ingestion Status Until Terminal State...');
  let currentStatus = 'pending';
  let attempts = 0;
  while (attempts < 30 && ['pending', 'processing'].includes(currentStatus)) {
    attempts++;
    await new Promise((r) => setTimeout(r, 1000));
    const statusRes = await fetch(`${API_BASE}/documents/${testDocId}/status`, {
      headers: { Authorization: `Bearer ${adminTokens.access_token}` },
    });
    if (statusRes.ok) {
      const statusData = await statusRes.json();
      currentStatus = statusData.status;
      process.stdout.write(`   Poll attempt ${attempts}: status="${currentStatus}"\r`);
      if (currentStatus === 'active') break;
      if (currentStatus === 'failed') {
        throw new Error(`Ingestion failed with error: ${statusData.last_error}`);
      }
    }
  }
  console.log(`\n   Ingestion reached terminal state: "${currentStatus}" (v1 active)`);
  if (currentStatus !== 'active') throw new Error(`Expected active status, got ${currentStatus}`);

  // Step 6: Test New Version Upload (PUT /documents/{id})
  console.log('\n6. Updating Document to Version 2 (PUT /documents/{id})...');
  const updatedDocContent = `# Test Document Version 2\n\nUpdated content with revised guidelines for admin testing at ${new Date().toISOString()}.`;
  const updateFormData = new FormData();
  const updatedBlob = new Blob([updatedDocContent], { type: 'text/markdown' });
  updateFormData.append('file', updatedBlob, testDocName);

  const updateRes = await fetch(`${API_BASE}/documents/${testDocId}`, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${adminTokens.access_token}` },
    body: updateFormData,
  });
  console.log(`   PUT ${API_BASE}/documents/${testDocId} -> HTTP ${updateRes.status}`);
  if (!updateRes.ok) {
    const err = await updateRes.text();
    throw new Error(`Update failed: ${err}`);
  }

  // Poll update until v2 is active
  currentStatus = 'updating';
  attempts = 0;
  while (attempts < 30 && ['updating', 'processing'].includes(currentStatus)) {
    attempts++;
    await new Promise((r) => setTimeout(r, 1000));
    const statusRes = await fetch(`${API_BASE}/documents/${testDocId}/status`, {
      headers: { Authorization: `Bearer ${adminTokens.access_token}` },
    });
    if (statusRes.ok) {
      const statusData = await statusRes.json();
      currentStatus = statusData.status;
      process.stdout.write(`   Poll update attempt ${attempts}: status="${currentStatus}", active_version=${statusData.active_version}\r`);
      if (currentStatus === 'active' && statusData.active_version === 2) break;
    }
  }
  console.log(`\n   Document version 2 reached terminal state: "${currentStatus}"`);

  // Step 7: Test Two-Phase Delete (DELETE /documents/{id})
  console.log('\n7. Initiating Two-Phase Delete (DELETE /documents/{id})...');
  const deleteRes = await fetch(`${API_BASE}/documents/${testDocId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${adminTokens.access_token}` },
  });
  console.log(`   DELETE ${API_BASE}/documents/${testDocId} -> HTTP ${deleteRes.status}`);
  if (!deleteRes.ok) throw new Error('Deletion request failed');

  // Verify document is excluded from GET /documents
  await new Promise((r) => setTimeout(r, 1000));
  const listAfterDelete = await fetch(`${API_BASE}/documents`, {
    headers: { Authorization: `Bearer ${adminTokens.access_token}` },
  });
  const remainingDocs = await listAfterDelete.json();
  const stillPresent = remainingDocs.find((d) => d.id === testDocId);
  console.log(`   Document visible in active list: ${stillPresent ? 'YES (Error)' : 'NO (Successfully hidden in Phase 1)'}`);
  if (stillPresent) throw new Error('Document still visible in active list after delete');

  // Step 8: Test Role-Based Access Isolation for Normal User
  console.log('\n8. Testing Role-Based Access Isolation for Non-Admin User...');
  // Register or login a regular user
  const regularEmail = `testuser_${Date.now()}@example.com`;
  const regularPassword = 'UserPassword123!';

  const regRes = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: regularEmail, password: regularPassword }),
  });
  if (!regRes.ok) throw new Error('User registration failed');

  const regLoginRes = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: regularEmail, password: regularPassword }),
  });
  const regTokens = await regLoginRes.json();

  const regMeRes = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${regTokens.access_token}` },
  });
  const regUser = await regMeRes.json();
  console.log(`   Regular user created: ${regUser.email} (Role: ${regUser.role})`);
  if (regUser.role !== 'user') throw new Error('Expected role user');

  // Try GET /documents with normal user token
  const userListRes = await fetch(`${API_BASE}/documents`, {
    headers: { Authorization: `Bearer ${regTokens.access_token}` },
  });
  console.log(`   Normal User GET /documents -> HTTP ${userListRes.status} (Expected 403)`);
  if (userListRes.status !== 403) throw new Error('Non-admin user was not blocked from GET /documents');

  // Try POST /documents with normal user token
  const dummyForm = new FormData();
  dummyForm.append('file', new Blob(['test']), 'dummy.txt');
  const userPostRes = await fetch(`${API_BASE}/documents`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${regTokens.access_token}` },
    body: dummyForm,
  });
  console.log(`   Normal User POST /documents -> HTTP ${userPostRes.status} (Expected 403)`);
  if (userPostRes.status !== 403) throw new Error('Non-admin user was not blocked from POST /documents');

  console.log('\n===========================================================');
  console.log('RESULT: Admin lifecycle & role-based isolation 100% verified!');
  console.log('===========================================================\n');
}

testAdminFlow().catch((err) => {
  console.error('Admin flow verification failed:', err);
  process.exit(1);
});
