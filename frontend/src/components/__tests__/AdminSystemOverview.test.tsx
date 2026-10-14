import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import AdminSystemOverview from '../AdminSystemOverview';
import * as api from '@/services/api';
import * as authContext from '@/context/AuthContext';
import {
  AdminSystemHealthResponse,
  SystemRoutesResponse,
  VectorStoreStatsResponse,
  ArchitectureOverviewResponse,
  WorkerStatsResponse,
  ChatQualityIndicatorsResponse,
  RecentActivityResponse,
  SystemSettingsResponse,
  SystemEnvironmentResponse,
} from '@/types/chat';

const mockAdminUser = {
  id: 'admin-1',
  email: 'admin@example.com',
  role: 'admin' as const,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const mockHealth: AdminSystemHealthResponse = {
  status: 'healthy',
  version: '1.0.0',
  checked_at: '2026-10-14T10:00:00Z',
  dependencies: {
    postgres: { name: 'PostgreSQL', status: 'healthy', latency_ms: 2.4 },
    redis: { name: 'Redis', status: 'healthy', latency_ms: 1.1 },
    qdrant: { name: 'Qdrant Vector DB', status: 'healthy', latency_ms: 5.8 },
  },
};

const mockRoutes: SystemRoutesResponse = {
  base_url: 'http://localhost:8000',
  docs_url: '/docs',
  redoc_url: '/redoc',
  openapi_url: '/openapi.json',
  health_url: '/health',
  routes: [
    { method: 'POST', path: '/api/v1/chat/stream', tags: ['chat'], summary: 'Stream chat', auth_level: 'user' },
    { method: 'POST', path: '/api/v1/auth/login', tags: ['auth'], summary: 'User login', auth_level: 'public' },
    { method: 'GET', path: '/api/v1/admin/system/health', tags: ['admin-system'], summary: 'System Health', auth_level: 'admin' },
  ],
};

const mockVectorStore: VectorStoreStatsResponse = {
  collection_name: 'documents',
  status: 'green',
  points_count: 1250,
  vectors_count: 1250,
  segments_count: 4,
  disk_data_size_bytes: 4194304,
  dense_dim: 768,
  has_sparse: true,
  indexed_documents_count: 15,
  active_versions_count: 15,
  superseded_versions_count: 3,
};

const mockArchitecture: ArchitectureOverviewResponse = {
  dense_model: 'sentence-transformers/all-mpnet-base-v2',
  dense_dim: 768,
  sparse_model: 'Qdrant/bm25',
  fusion_method: 'Reciprocal Rank Fusion (RRF)',
  rrf_k: 60,
  retrieval_top_k: 20,
  reranker_model: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
  reranker_threshold: 0.5,
  rerank_top_n: 4,
  chunk_size: 512,
  chunk_overlap: 50,
  history_window: 6,
  guardrail_layers: [
    'Layer 1: Reranker confidence score check',
    'Layer 2: Sentinel canary injection & cross-chunk validation',
    'Layer 3: Hallucinated citation pruning & retraction',
  ],
  fallback_message: "I don't have enough verified information to answer this question.",
};

const mockWorkers: WorkerStatsResponse = {
  online_workers_count: 1,
  worker_names: ['celery@worker-1'],
  active_tasks_count: 0,
  queue_length: 0,
  last_beat_run: '2026-10-14T09:59:00Z',
  last_reconciler_run: '2026-10-14T09:55:00Z',
  reconciler_fixed_count: 0,
  reconciler_last_status: 'success',
  failed_ingestions_count: 0,
};

const mockQuality: ChatQualityIndicatorsResponse = {
  window: '24h',
  total_queries: 100,
  fallback_count: 5,
  fallback_rate: 0.05,
  layer1_fallback_count: 3,
  layer2_fallback_count: 1,
  layer3_fallback_count: 1,
  avg_retrieval_score: 0.82,
  queries_with_no_sources: 0,
};

const mockActivity: RecentActivityResponse = {
  audit_logs: [
    {
      id: 'log-1',
      user_id: 'admin-1',
      user_email: 'admin@example.com',
      action: 'SYSTEM_SETTINGS_UPDATE',
      target_type: 'system_settings',
      target_id: '1',
      details: { reranker_threshold: 0.65 },
      created_at: '2026-10-14T09:40:00Z',
    },
  ],
  recent_errors: [],
};

const mockSettings: SystemSettingsResponse = {
  reranker_threshold: 0.7,
  retrieval_top_k: 20,
  rerank_top_n: 4,
  history_messages: 6,
  rate_limit_per_minute: 60,
  rate_limit_login_per_minute: 10,
  sse_keepalive_interval: 15,
  max_upload_size_bytes: 10485760,
  version: 1,
  updated_at: '2026-10-14T09:00:00Z',
};

const mockEnvironment: SystemEnvironmentResponse = {
  settings: [
    { key: 'APP_ENV', value: 'production', description: 'Deployment runtime environment' },
    { key: 'PROJECT_NAME', value: 'AI Chatbot', description: 'Application service branding' },
    { key: 'QDRANT_COLLECTION', value: 'documents', description: 'Active Qdrant collection' },
  ],
};

describe('AdminSystemOverview Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.spyOn(authContext, 'useAuth').mockReturnValue({
      user: mockAdminUser,
      token: 'admin-token',
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
      register: vi.fn(),
      refreshToken: vi.fn(),
    });

    vi.spyOn(api, 'fetchSystemHealth').mockResolvedValue(mockHealth);
    vi.spyOn(api, 'fetchSystemRoutes').mockResolvedValue(mockRoutes);
    vi.spyOn(api, 'fetchVectorStoreStats').mockResolvedValue(mockVectorStore);
    vi.spyOn(api, 'fetchArchitectureOverview').mockResolvedValue(mockArchitecture);
    vi.spyOn(api, 'fetchWorkerStats').mockResolvedValue(mockWorkers);
    vi.spyOn(api, 'fetchChatQualityIndicators').mockResolvedValue(mockQuality);
    vi.spyOn(api, 'fetchRecentActivity').mockResolvedValue(mockActivity);
    vi.spyOn(api, 'fetchSystemSettings').mockResolvedValue(mockSettings);
    vi.spyOn(api, 'fetchSystemEnvironment').mockResolvedValue(mockEnvironment);
    vi.spyOn(api, 'updateSystemSettings').mockResolvedValue({
      ...mockSettings,
      reranker_threshold: 0.65,
      version: 2,
    });
    vi.spyOn(api, 'resetSystemSettings').mockResolvedValue({
      ...mockSettings,
      version: 3,
    });
  });

  it('renders all 9 sections after loading data', async () => {
    render(<AdminSystemOverview />);

    await waitFor(() => {
      expect(screen.getByText('Service Dependencies & Live Round-Trip Latency')).toBeInTheDocument();
      expect(screen.getByText('Runtime Editable Settings (Hot-Reloaded)')).toBeInTheDocument();
      expect(screen.getByText('Core Architecture Parameters')).toBeInTheDocument();
      expect(screen.getByText('Vector Store Synchronization')).toBeInTheDocument();
      expect(screen.getByText('Background Workers & Document Reconciler')).toBeInTheDocument();
      expect(screen.getByText('Chat Quality & Guardrail Telemetry')).toBeInTheDocument();
      expect(screen.getByText(/Registered API Routes/)).toBeInTheDocument();
      expect(screen.getByText('Recent Admin Audit Trail & Errors')).toBeInTheDocument();
      expect(screen.getByText('Environment & Infrastructure Inspection')).toBeInTheDocument();
    });

    // Check dependency latencies
    expect(screen.getByText('PostgreSQL')).toBeInTheDocument();
    expect(screen.getByText('2.4')).toBeInTheDocument();
    expect(screen.getByText('Redis')).toBeInTheDocument();
    expect(screen.getByText('1.1')).toBeInTheDocument();
    expect(screen.getByText('Qdrant Vector DB')).toBeInTheDocument();
    expect(screen.getByText('5.8')).toBeInTheDocument();
  });

  it('displays prominent grounding warning alert when threshold is reduced below 0.5', async () => {
    render(<AdminSystemOverview />);

    await waitFor(() => {
      expect(screen.getByText('Runtime Editable Settings (Hot-Reloaded)')).toBeInTheDocument();
    });

    const thresholdInput = screen.getByLabelText(/Reranker Threshold/i);
    expect(thresholdInput).toBeInTheDocument();

    // Change threshold to 0.4
    fireEvent.change(thresholdInput, { target: { value: '0.4' } });

    await waitFor(() => {
      expect(screen.getByText('⚠️ Grounding Guardrail Alert')).toBeInTheDocument();
      expect(
        screen.getByText(/below standard 0\.50/i)
      ).toBeInTheDocument();
    });
  });

  it('validates invariant: rerank_top_n cannot exceed retrieval_top_k', async () => {
    render(<AdminSystemOverview />);

    await waitFor(() => {
      expect(screen.getByText('Runtime Editable Settings (Hot-Reloaded)')).toBeInTheDocument();
    });

    const topKInput = screen.getByLabelText(/Retrieval Top K/i);
    const topNInput = screen.getByLabelText(/Rerank Top N/i);

    // Set top_k to 5 and top_n to 10 (invalid invariant)
    fireEvent.change(topKInput, { target: { value: '5' } });
    fireEvent.change(topNInput, { target: { value: '10' } });

    await waitFor(() => {
      expect(
        screen.getByText(/Rerank Top N cannot exceed Retrieval Top K/i)
      ).toBeInTheDocument();
    });

    const saveButton = screen.getByRole('button', { name: /Save Runtime Settings/i });
    expect(saveButton).toBeDisabled();
    expect(api.updateSystemSettings).not.toHaveBeenCalled();
  });

  it('successfully updates runtime settings', async () => {
    render(<AdminSystemOverview />);

    await waitFor(() => {
      expect(screen.getByText('Runtime Editable Settings (Hot-Reloaded)')).toBeInTheDocument();
    });

    const thresholdInput = screen.getByLabelText(/Reranker Threshold/i);
    fireEvent.change(thresholdInput, { target: { value: '0.65' } });

    const saveButton = screen.getByRole('button', { name: /Save Runtime Settings/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(api.updateSystemSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          reranker_threshold: 0.65,
        })
      );
      expect(screen.getByText(/System settings updated successfully to version v2/i)).toBeInTheDocument();
    });
  });

  it('opens confirmation modal and resets settings to defaults', async () => {
    render(<AdminSystemOverview />);

    await waitFor(() => {
      expect(screen.getByText('Runtime Editable Settings (Hot-Reloaded)')).toBeInTheDocument();
    });

    const resetButton = screen.getByRole('button', { name: /Reset to Environment Defaults/i });
    fireEvent.click(resetButton);

    // Modal appears
    await waitFor(() => {
      expect(screen.getByText('Reset System Settings to Defaults?')).toBeInTheDocument();
    });

    // Confirm reset
    const confirmButton = screen.getByRole('button', { name: /Confirm Reset/i });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(api.resetSystemSettings).toHaveBeenCalled();
      expect(screen.getByText(/System settings reset to baseline defaults \(v3\)\./i)).toBeInTheDocument();
    });
  });
});
