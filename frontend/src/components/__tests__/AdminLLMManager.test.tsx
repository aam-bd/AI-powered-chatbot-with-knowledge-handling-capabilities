import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import AdminLLMManager from '../AdminLLMManager';
import * as api from '@/services/api';
import * as authContext from '@/context/AuthContext';
import { LLMProvider, LLMSettings, ProviderModel, LLMUsageResponse } from '@/types/chat';

// Mock Lucide icons that may have issues in jsdom
vi.mock('lucide-react', async () => {
  const actual = await vi.importActual('lucide-react');
  return {
    ...actual,
  };
});

const mockAdminUser = {
  id: 'admin-1',
  email: 'admin@example.com',
  role: 'admin' as const,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const mockRegularUser = {
  id: 'user-1',
  email: 'user@example.com',
  role: 'user' as const,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const mockProviders: LLMProvider[] = [
  {
    id: 'prov-openai',
    name: 'OpenAI GPT-4o',
    provider_type: 'openai',
    base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-4o-mini',
    is_active: true,
    is_fallback: false,
    has_api_key: true,
    api_key_masked_hint: '••••k123',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'prov-gemini',
    name: 'Google Gemini',
    provider_type: 'gemini',
    base_url: 'https://generativelanguage.googleapis.com',
    default_model: 'gemini-1.5-flash',
    is_active: false,
    is_fallback: true,
    has_api_key: true,
    api_key_masked_hint: '••••g987',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'prov-ollama',
    name: 'Local Ollama',
    provider_type: 'ollama',
    base_url: 'http://localhost:11434/v1',
    default_model: 'llama3:8b',
    is_active: false,
    is_fallback: false,
    has_api_key: false,
    api_key_masked_hint: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
];

const mockCatalogModels: ProviderModel[] = [
  {
    id: 'pm-1',
    provider_id: 'prov-openai',
    model_id: 'gpt-4o',
    display_name: 'GPT-4o Omnimodel',
    context_length: 128000,
    max_output_tokens: 4096,
    is_enabled: true,
    is_available: true,
    price_prompt_per_1m: 2.5,
    price_completion_per_1m: 10.0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'pm-2',
    provider_id: 'prov-openai',
    model_id: 'gpt-4o-mini',
    display_name: 'GPT-4o Mini',
    context_length: 128000,
    max_output_tokens: 4096,
    is_enabled: true,
    is_available: true,
    price_prompt_per_1m: 0.15,
    price_completion_per_1m: 0.60,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'pm-3',
    provider_id: 'prov-openai',
    model_id: 'chatgpt-custom',
    display_name: 'Custom Finetune',
    context_length: 32000,
    max_output_tokens: 2048,
    is_enabled: false,
    is_available: true,
    price_prompt_per_1m: null,
    price_completion_per_1m: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
];

const mockUsage: LLMUsageResponse = {
  window: '24h',
  total_requests: 42,
  total_prompt_tokens: 15420,
  total_completion_tokens: 5210,
  total_tokens: 20630,
  total_errors: 1,
  total_estimated_cost: 0.0825,
  avg_latency_ms: 654,
  items: [
    {
      provider_id: 'prov-openai',
      provider_name: 'OpenAI Production',
      model_id: 'gpt-4o-mini',
      total_requests: 42,
      total_prompt_tokens: 15420,
      total_completion_tokens: 5210,
      total_errors: 1,
      estimated_cost: 0.0825,
      avg_latency_ms: 654,
    },
  ],
};

const mockSettings: LLMSettings = {
  active_provider_id: 'prov-openai',
  active_model: 'gpt-4o-mini',
  fallback_provider_id: 'prov-gemini',
  fallback_model: 'gemini-1.5-flash',
  temperature: 0.2,
  max_tokens: 1024,
  timeout_seconds: 30,
};

const mockHealth = {
  status: 'healthy',
  version: '1.0.0',
  embedding_model: 'text-embedding-3-small',
  reranker_model: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
};

describe('AdminLLMManager Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(authContext, 'useAuth').mockReturnValue({
      user: mockAdminUser,
      accessToken: 'test-token',
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
      refreshAuth: vi.fn(),
    });
    vi.spyOn(api, 'fetchLLMProviders').mockResolvedValue(mockProviders);
    vi.spyOn(api, 'fetchLLMSettings').mockResolvedValue(mockSettings);
    vi.spyOn(api, 'fetchHealth').mockResolvedValue(mockHealth);
    vi.spyOn(api, 'fetchProviderCatalog').mockResolvedValue(mockCatalogModels);
    vi.spyOn(api, 'fetchLLMUsage').mockResolvedValue(mockUsage);
  });

  it('renders access denied for non-admin users', () => {
    vi.spyOn(authContext, 'useAuth').mockReturnValue({
      user: mockRegularUser,
      accessToken: 'test-token',
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
      refreshAuth: vi.fn(),
    });

    render(<AdminLLMManager />);
    expect(screen.getByText(/Administrator Privileges Required/i)).toBeInTheDocument();
    expect(screen.queryByText('LLM Providers')).not.toBeInTheDocument();
  });

  it('renders LLM management dashboard for admin users', async () => {
    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText('LLM Providers')).toBeInTheDocument();
    });

    expect(screen.getByText('OpenAI GPT-4o')).toBeInTheDocument();
    expect(screen.getByText('Google Gemini')).toBeInTheDocument();
    expect(screen.getByText('Local Ollama')).toBeInTheDocument();

    // Verify read-only models section
    expect(screen.getByText('text-embedding-3-small')).toBeInTheDocument();
    expect(screen.getByText('cross-encoder/ms-marco-MiniLM-L-6-v2')).toBeInTheDocument();
  });

  it('uses password input type for API key with no prefilled value', async () => {
    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText('Add Provider')).toBeInTheDocument();
    });

    // Open Add Provider modal
    fireEvent.click(screen.getByText('Add Provider'));

    const apiKeyInput = screen.getByPlaceholderText(/Enter API key/i) as HTMLInputElement;
    expect(apiKeyInput).toBeInTheDocument();
    expect(apiKeyInput.type).toBe('password');
    expect(apiKeyInput.getAttribute('autocomplete')).toBe('new-password');
    expect(apiKeyInput.value).toBe('');
  });

  it('shows masked hint in edit mode and preserves existing key if left empty', async () => {
    const updateSpy = vi.spyOn(api, 'updateLLMProvider').mockResolvedValue(mockProviders[0]);

    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText('OpenAI GPT-4o')).toBeInTheDocument();
    });

    // Find and click the Edit button for OpenAI provider
    const editButtons = screen.getAllByTitle('Edit Provider');
    fireEvent.click(editButtons[0]);

    // Check modal displays masked hint
    expect(screen.getByText(/Key configured: ••••k123/i)).toBeInTheDocument();

    // Check placeholder indicates keeping key
    const apiKeyInput = screen.getByPlaceholderText(/Leave empty to keep existing key/i) as HTMLInputElement;
    expect(apiKeyInput.value).toBe('');

    // Change the name and save without typing an API key
    const nameInput = screen.getByDisplayValue('OpenAI GPT-4o');
    fireEvent.change(nameInput, { target: { value: 'OpenAI GPT-4o Updated' } });

    // Submit
    fireEvent.click(screen.getByText('Save Provider'));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(
        'prov-openai',
        expect.not.objectContaining({ api_key: expect.anything(), clear_api_key: expect.anything() })
      );
    });
  });

  it('triggers clear_api_key when clearing key in edit modal', async () => {
    const updateSpy = vi.spyOn(api, 'updateLLMProvider').mockResolvedValue({
      ...mockProviders[1],
      has_api_key: false,
      api_key_masked_hint: null,
    });

    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText('Google Gemini')).toBeInTheDocument();
    });

    // Edit Google Gemini
    const editButtons = screen.getAllByTitle('Edit Provider');
    fireEvent.click(editButtons[1]);

    // Click "Clear Key"
    const clearKeyBtn = screen.getByText('Clear Key');
    fireEvent.click(clearKeyBtn);

    // Confirmation modal should appear
    expect(screen.getByText(/Remove API Key\?/i)).toBeInTheDocument();
    const confirmClearBtn = screen.getByText('Yes, Clear Key');
    fireEvent.click(confirmClearBtn);

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith('prov-gemini', { clear_api_key: true });
    });
  });

  it('displays 409 error when deleting active or fallback provider', async () => {
    vi.spyOn(api, 'deleteLLMProvider').mockRejectedValue(
      new Error('Cannot delete provider "prov-openai": it is currently configured as the active LLM provider (HTTP 409)')
    );

    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText('OpenAI GPT-4o')).toBeInTheDocument();
    });

    // Attempt to delete active provider
    const deleteButtons = screen.getAllByTitle('Delete Provider');
    fireEvent.click(deleteButtons[0]);

    // Confirm in modal
    expect(screen.getByText(/Delete Provider\?/i)).toBeInTheDocument();
    const confirmDeleteBtn = screen.getByText('Delete Permanently');
    fireEvent.click(confirmDeleteBtn);

    await waitFor(() => {
      expect(screen.getByText(/Cannot delete provider/i)).toBeInTheDocument();
    });
  });

  it('fetches models dynamically and populates model dropdown', async () => {
    vi.spyOn(api, 'fetchLLMModels').mockResolvedValue({
      provider_id: 'prov-openai',
      models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
      cached: false,
    });

    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText('OpenAI GPT-4o')).toBeInTheDocument();
    });

    // Open edit modal for OpenAI
    const editButtons = screen.getAllByTitle('Edit Provider');
    fireEvent.click(editButtons[0]);

    // Click "Fetch Models"
    const fetchModelsBtn = screen.getByText('Fetch Models');
    fireEvent.click(fetchModelsBtn);

    await waitFor(() => {
      expect(api.fetchLLMModels).toHaveBeenCalledWith('prov-openai');
      expect(screen.getByDisplayValue(/gpt-4-turbo/)).toBeInTheDocument();
    });
  });

  it('saves runtime settings and shows hot reload confirmation', async () => {
    const updateSettingsSpy = vi.spyOn(api, 'updateLLMSettings').mockResolvedValue({
      ...mockSettings,
      temperature: 0.5,
    });

    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText(/Save & Hot Reload/i)).toBeInTheDocument();
    });

    // Change temperature slider/input
    const slider = document.querySelector('input[type="range"]') as HTMLInputElement;
    fireEvent.change(slider, { target: { value: '0.5' } });

    // Click Save
    const saveSettingsBtn = screen.getByText(/Save & Hot Reload/i);
    fireEvent.click(saveSettingsBtn);

    await waitFor(() => {
      expect(updateSettingsSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          temperature: 0.5,
        })
      );
      expect(screen.getByText(/LLM settings successfully updated/i)).toBeInTheDocument();
    });
  });

  it('toggles base URL lock/unlock when creating preset provider', async () => {
    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText('Add Provider')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Add Provider'));

    // Base URL should initially be read-only for presets
    const urlInput = screen.getByPlaceholderText('https://api.openai.com/v1') as HTMLInputElement;
    expect(urlInput.readOnly).toBe(true);
    expect(screen.getByText('Unlock to edit')).toBeInTheDocument();

    // Click Unlock
    fireEvent.click(screen.getByText('Unlock to edit'));
    expect(urlInput.readOnly).toBe(false);
    expect(screen.getByText('Lock URL')).toBeInTheDocument();
  });

  it('calls restorePresetProviders and displays success banner', async () => {
    const restoreSpy = vi.spyOn(api, 'restorePresetProviders').mockResolvedValue(mockProviders);

    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText('Restore Presets')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Restore Presets'));

    await waitFor(() => {
      expect(restoreSpy).toHaveBeenCalledTimes(1);
      expect(screen.getByText(/Preset providers restored successfully/i)).toBeInTheDocument();
    });
  });

  it('opens model catalog, filters models, and toggles model enablement', async () => {
    const updateModelSpy = vi.spyOn(api, 'updateProviderModel').mockResolvedValue({
      ...mockCatalogModels[2],
      is_enabled: true,
    });

    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText('OpenAI GPT-4o')).toBeInTheDocument();
    });

    // Click catalog button for OpenAI
    const catalogBtns = screen.getAllByRole('button', { name: /Catalog/i });
    fireEvent.click(catalogBtns[0]);

    // Model catalog modal should open
    await waitFor(() => {
      expect(screen.getByText(/Model Catalog: OpenAI GPT-4o/i)).toBeInTheDocument();
      expect(screen.getByText('GPT-4o Omnimodel')).toBeInTheDocument();
      expect(screen.getByText('chatgpt-custom')).toBeInTheDocument();
    });

    // Test filter search
    const searchInput = screen.getByPlaceholderText(/Filter models by identifier or name/i);
    fireEvent.change(searchInput, { target: { value: 'custom' } });
    expect(screen.queryByText('GPT-4o Omnimodel')).not.toBeInTheDocument();
    expect(screen.getByText('chatgpt-custom')).toBeInTheDocument();

    // Toggle enablement on chatgpt-custom
    const checkboxes = screen.getAllByRole('checkbox');
    // First checkbox in filtered table is for chatgpt-custom
    fireEvent.click(checkboxes[0]);

    await waitFor(() => {
      expect(updateModelSpy).toHaveBeenCalledWith('prov-openai', 'chatgpt-custom', { is_enabled: true });
    });
  });

  it('renders LLM usage metrics and supports switching time ranges', async () => {
    const fetchUsageSpy = vi.spyOn(api, 'fetchLLMUsage');

    render(<AdminLLMManager />);

    await waitFor(() => {
      expect(screen.getByText(/LLM Generation Usage & Cost Tracking/i)).toBeInTheDocument();
    });

    // Verify initial 24h metrics rendered
    expect(screen.getAllByText('42')[0]).toBeInTheDocument(); // total requests
    expect(screen.getAllByText('15,420')[0]).toBeInTheDocument(); // prompt tokens
    expect(screen.getAllByText('$0.0825')[0]).toBeInTheDocument(); // total cost

    // Click 7D filter
    fireEvent.click(screen.getByText('7D'));

    await waitFor(() => {
      expect(fetchUsageSpy).toHaveBeenCalledWith('7d');
    });
  });
});
