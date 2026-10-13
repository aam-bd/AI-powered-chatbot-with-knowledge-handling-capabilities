'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  LLMProvider,
  LLMSettings,
  LLMProviderCreateInput,
  LLMProviderUpdateInput,
  HealthInfo,
} from '@/types/chat';
import {
  fetchLLMProviders,
  createLLMProvider,
  updateLLMProvider,
  deleteLLMProvider,
  testLLMProvider,
  fetchLLMModels,
  fetchLLMSettings,
  updateLLMSettings,
  fetchHealth,
} from '@/services/api';
import {
  Cpu,
  Layers,
  Sparkles,
  Server,
  Plus,
  RefreshCw,
  Trash2,
  Edit,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  Check,
  X,
  ExternalLink,
  Info,
  Key,
  Shield,
  ShieldAlert,
  Sliders,
  SlidersHorizontal,
} from 'lucide-react';
import { useAuth } from '@/context/AuthContext';

interface PresetConfig {
  label: string;
  provider_type: string;
  default_url: string;
  suggested_models: string[];
  key_required: boolean;
}

const PRESETS: Record<string, PresetConfig> = {
  openai_compatible: {
    label: 'OpenAI',
    provider_type: 'openai_compatible',
    default_url: 'https://api.openai.com/v1',
    suggested_models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
    key_required: true,
  },
  gemini: {
    label: 'Google Gemini (OpenAI Endpoint)',
    provider_type: 'openai_compatible',
    default_url: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    suggested_models: ['gemini-2.5-pro', 'gemini-3.1-flash-lite', 'gemini-1.5-flash'],
    key_required: true,
  },
  anthropic: {
    label: 'Anthropic Claude',
    provider_type: 'anthropic',
    default_url: 'https://api.anthropic.com',
    suggested_models: ['claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022', 'claude-3-opus-20240229'],
    key_required: true,
  },
  openrouter: {
    label: 'OpenRouter',
    provider_type: 'openai_compatible',
    default_url: 'https://openrouter.ai/api/v1',
    suggested_models: [
      'meta-llama/llama-3.3-70b-instruct',
      'anthropic/claude-3.5-sonnet',
      'deepseek/deepseek-chat',
    ],
    key_required: true,
  },
  ollama: {
    label: 'Ollama (Local)',
    provider_type: 'openai_compatible',
    default_url: 'http://localhost:11434/v1',
    suggested_models: ['llama3.2', 'mistral', 'qwen2.5', 'llama3.1'],
    key_required: false,
  },
  custom: {
    label: 'Custom Provider',
    provider_type: 'openai_compatible',
    default_url: 'https://',
    suggested_models: ['custom-model'],
    key_required: false,
  },
};

export default function AdminLLMManager() {
  const { user } = useAuth();

  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Success / error banners
  const [successBanner, setSuccessBanner] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Connection testing state (maps provider ID -> isTesting boolean)
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResultModal, setTestResultModal] = useState<{
    providerName: string;
    success: boolean;
    message: string;
    sanitizedError?: string | null;
  } | null>(null);

  // Add / Edit Modal state
  const [modalMode, setModalMode] = useState<'create' | 'edit' | null>(null);
  const [editingProvider, setEditingProvider] = useState<LLMProvider | null>(null);
  const [selectedPreset, setSelectedPreset] = useState<string>('openai_compatible');
  const [formName, setFormName] = useState('');
  const [formBaseUrl, setFormBaseUrl] = useState('');
  const [formApiKey, setFormApiKey] = useState('');
  const [formModelsText, setFormModelsText] = useState('');
  const [formDefaultModel, setFormDefaultModel] = useState('');
  const [formIsEnabled, setFormIsEnabled] = useState(true);
  const [isSavingProvider, setIsSavingProvider] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  // Clear Key Confirmation Modal
  const [clearKeyModalProvider, setClearKeyModalProvider] = useState<LLMProvider | null>(null);
  const [isClearingKey, setIsClearingKey] = useState(false);

  // Delete Provider Confirmation Modal
  const [deleteModalProvider, setDeleteModalProvider] = useState<LLMProvider | null>(null);
  const [isDeletingProvider, setIsDeletingProvider] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Runtime Settings Form State
  const [selectedActiveProviderId, setSelectedActiveProviderId] = useState<string>('');
  const [selectedActiveModel, setSelectedActiveModel] = useState<string>('');
  const [selectedFallbackProviderId, setSelectedFallbackProviderId] = useState<string>('none');
  const [selectedFallbackModel, setSelectedFallbackModel] = useState<string>('');
  const [temperature, setTemperature] = useState<number>(0.2);
  const [maxTokens, setMaxTokens] = useState<number>(1024);
  const [isSavingSettings, setIsSavingSettings] = useState(false);

  // Dynamic models fetched for runtime selectors
  const [activeProviderModels, setActiveProviderModels] = useState<string[]>([]);
  const [fallbackProviderModels, setFallbackProviderModels] = useState<string[]>([]);

  // Load all initial data
  const loadData = useCallback(async (quiet = false) => {
    if (!user || user.role !== 'admin') {
      setIsLoading(false);
      return;
    }
    if (!quiet) setIsLoading(true);
    else setIsRefreshing(true);
    setErrorBanner(null);

    try {
      const [providersData, settingsData, healthData] = await Promise.all([
        fetchLLMProviders(),
        fetchLLMSettings(),
        fetchHealth().catch(() => null),
      ]);

      setProviders(providersData);
      setSettings(settingsData);
      setHealth(healthData);

      // Initialize settings form values
      if (settingsData) {
        const activeProv = providersData.find((p) => p.id === settingsData.active_provider_id);
        const fallbackProv = providersData.find((p) => p.id === settingsData.fallback_provider_id);
        setSelectedActiveProviderId(settingsData.active_provider_id);
        setSelectedActiveModel(settingsData.active_model || activeProv?.default_model || '');
        setSelectedFallbackProviderId(settingsData.fallback_provider_id || 'none');
        setSelectedFallbackModel(settingsData.fallback_model || fallbackProv?.default_model || '');
        setTemperature(settingsData.temperature);
        setMaxTokens(settingsData.max_tokens);
      }
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to load LLM configurations');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [user]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Load models for active provider selection
  useEffect(() => {
    if (!selectedActiveProviderId) {
      setActiveProviderModels([]);
      return;
    }
    const found = providers.find((p) => p.id === selectedActiveProviderId);
    if (!found) return;

    fetchLLMModels(selectedActiveProviderId)
      .then((res) => {
        const fallbackList = found.models && Array.isArray(found.models) && found.models.length > 0
          ? found.models
          : [found.default_model];
        const modelsList = res.models && res.models.length > 0 ? res.models : fallbackList;
        setActiveProviderModels(modelsList);
        if (!modelsList.includes(selectedActiveModel)) {
          setSelectedActiveModel(modelsList[0] || found.default_model);
        }
      })
      .catch(() => {
        const fallbackList = found.models && Array.isArray(found.models) && found.models.length > 0
          ? found.models
          : [found.default_model];
        setActiveProviderModels(fallbackList);
        if (!fallbackList.includes(selectedActiveModel)) {
          setSelectedActiveModel(found.default_model);
        }
      });
  }, [selectedActiveProviderId, providers]);

  // Load models for fallback provider selection
  useEffect(() => {
    if (!selectedFallbackProviderId || selectedFallbackProviderId === 'none') {
      setFallbackProviderModels([]);
      setSelectedFallbackModel('');
      return;
    }
    const found = providers.find((p) => p.id === selectedFallbackProviderId);
    if (!found) return;

    fetchLLMModels(selectedFallbackProviderId)
      .then((res) => {
        const fallbackList = found.models && Array.isArray(found.models) && found.models.length > 0
          ? found.models
          : [found.default_model];
        const modelsList = res.models && res.models.length > 0 ? res.models : fallbackList;
        setFallbackProviderModels(modelsList);
        if (!modelsList.includes(selectedFallbackModel)) {
          setSelectedFallbackModel(modelsList[0] || found.default_model);
        }
      })
      .catch(() => {
        const fallbackList = found.models && Array.isArray(found.models) && found.models.length > 0
          ? found.models
          : [found.default_model];
        setFallbackProviderModels(fallbackList);
        if (!fallbackList.includes(selectedFallbackModel)) {
          setSelectedFallbackModel(found.default_model);
        }
      });
  }, [selectedFallbackProviderId, providers]);

  // Check if runtime settings are dirty / modified
  const isSettingsModified = useMemo(() => {
    if (!settings) return false;
    const fbProv = selectedFallbackProviderId === 'none' ? null : selectedFallbackProviderId;
    const fbModel = fbProv ? selectedFallbackModel : null;
    return (
      selectedActiveProviderId !== settings.active_provider_id ||
      selectedActiveModel !== settings.active_model ||
      fbProv !== settings.fallback_provider_id ||
      fbModel !== settings.fallback_model ||
      temperature !== settings.temperature ||
      maxTokens !== settings.max_tokens
    );
  }, [
    settings,
    selectedActiveProviderId,
    selectedActiveModel,
    selectedFallbackProviderId,
    selectedFallbackModel,
    temperature,
    maxTokens,
  ]);

  // Validate settings form
  const isSettingsValid = useMemo(() => {
    if (!selectedActiveProviderId || !selectedActiveModel) return false;
    if (temperature < 0.0 || temperature > 2.0) return false;
    if (maxTokens < 1 || maxTokens > 8192) return false;
    if (selectedFallbackProviderId !== 'none' && !selectedFallbackModel) return false;
    return true;
  }, [
    selectedActiveProviderId,
    selectedActiveModel,
    temperature,
    maxTokens,
    selectedFallbackProviderId,
    selectedFallbackModel,
  ]);

  // Active provider status check
  const activeProvider = useMemo(() => {
    if (!settings) return null;
    return providers.find((p) => p.id === settings.active_provider_id);
  }, [settings, providers]);

  const hasWarning = useMemo(() => {
    if (!providers || providers.length === 0) return true;
    if (!activeProvider || activeProvider.is_enabled === false) return true;
    if (activeProvider.last_test_status === 'failed') return true;
    return false;
  }, [providers, activeProvider]);

  // Save runtime settings
  const handleSaveSettings = async () => {
    if (!isSettingsValid || !isSettingsModified) return;
    setIsSavingSettings(true);
    setErrorBanner(null);
    setSuccessBanner(null);

    const payload = {
      active_provider_id: selectedActiveProviderId,
      active_model: selectedActiveModel,
      fallback_provider_id: selectedFallbackProviderId === 'none' ? null : selectedFallbackProviderId,
      fallback_model: selectedFallbackProviderId === 'none' ? null : selectedFallbackModel,
      temperature,
      max_tokens: maxTokens,
    };

    try {
      const updated = await updateLLMSettings(payload);
      setSettings(updated);
      setSuccessBanner(
        `LLM settings successfully updated to version ${updated.version}. New chat requests will use ${updated.active_model}.`
      );
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to update LLM settings');
    } finally {
      setIsSavingSettings(false);
    }
  };

  // Run test connection
  const handleTestConnection = async (provider: LLMProvider) => {
    setTestingId(provider.id);
    setErrorBanner(null);
    setSuccessBanner(null);

    try {
      const result = await testLLMProvider(provider.id);
      setTestResultModal({
        providerName: provider.name,
        success: result.success,
        message: result.message,
        sanitizedError: result.sanitized_error,
      });

      // Update provider in local list with new test status
      setProviders((prev) =>
        prev.map((p) =>
          p.id === provider.id
            ? {
                ...p,
                last_test_status: result.success ? 'success' : 'failed',
                last_test_at: new Date().toISOString(),
              }
            : p
        )
      );
    } catch (err: any) {
      setTestResultModal({
        providerName: provider.name,
        success: false,
        message: 'Connection test request failed',
        sanitizedError: err.message || 'Unexpected network error during test request.',
      });
    } finally {
      setTestingId(null);
    }
  };

  // Open Create Modal
  const handleOpenCreateModal = () => {
    setModalError(null);
    setSelectedPreset('openai_compatible');
    const preset = PRESETS['openai_compatible'];
    setFormName('');
    setFormBaseUrl(preset.default_url);
    setFormApiKey('');
    setFormModelsText(preset.suggested_models.join(', '));
    setFormDefaultModel(preset.suggested_models[0] || '');
    setFormIsEnabled(true);
    setEditingProvider(null);
    setModalMode('create');
  };

  // Open Edit Modal
  const handleOpenEditModal = (provider: LLMProvider) => {
    setModalError(null);
    setEditingProvider(provider);
    setFormName(provider.name);
    setFormBaseUrl(provider.base_url);
    setFormApiKey(''); // Secret hygiene: NEVER prefill API key
    const currentModels = provider.models && Array.isArray(provider.models) && provider.models.length > 0
      ? provider.models
      : [provider.default_model];
    setFormModelsText(currentModels.join(', '));
    setFormDefaultModel(provider.default_model);
    setFormIsEnabled(provider.is_enabled ?? true);
    setSelectedPreset('custom');
    setModalMode('edit');
  };

  // Handle Preset Selection Change
  const handlePresetChange = (presetKey: string) => {
    setSelectedPreset(presetKey);
    const preset = PRESETS[presetKey];
    if (preset) {
      setFormBaseUrl(preset.default_url);
      setFormModelsText(preset.suggested_models.join(', '));
      setFormDefaultModel(preset.suggested_models[0] || '');
      if (modalMode === 'create' && !formName) {
        setFormName(preset.label);
      }
    }
  };

  // Close and clean Add/Edit Modal
  const handleCloseModal = () => {
    setModalMode(null);
    setEditingProvider(null);
    setFormApiKey(''); // Secret hygiene: wipe key on unmount / close
    setModalError(null);
  };

  // Submit Add / Edit Provider Form
  const handleSubmitProvider = async (e: React.FormEvent) => {
    e.preventDefault();
    setModalError(null);
    setIsSavingProvider(true);

    const parsedModels = formModelsText
      .split(',')
      .map((m) => m.trim())
      .filter(Boolean);

    if (parsedModels.length === 0) {
      setModalError('At least one model identifier must be specified.');
      setIsSavingProvider(false);
      return;
    }

    const defaultModel = formDefaultModel.trim() || parsedModels[0];
    if (!parsedModels.includes(defaultModel)) {
      setModalError(`Default model "${defaultModel}" must be one of the models listed.`);
      setIsSavingProvider(false);
      return;
    }

    try {
      if (modalMode === 'create') {
        const payload: LLMProviderCreateInput = {
          name: formName.trim(),
          provider_type: PRESETS[selectedPreset]?.provider_type || 'openai_compatible',
          base_url: formBaseUrl.trim(),
          api_key: formApiKey.trim() || undefined,
          models: parsedModels,
          default_model: defaultModel,
          is_enabled: formIsEnabled,
        };

        const created = await createLLMProvider(payload);
        setProviders((prev) => [...prev, created]);
        setSuccessBanner(`Successfully registered provider "${created.name}".`);
        handleCloseModal();
      } else if (modalMode === 'edit' && editingProvider) {
        const payload: LLMProviderUpdateInput = {
          name: formName.trim(),
          base_url: formBaseUrl.trim(),
          models: parsedModels,
          default_model: defaultModel,
          is_enabled: formIsEnabled,
        };
        // Secret hygiene: Send key ONLY if newly typed
        if (formApiKey.trim()) {
          payload.api_key = formApiKey.trim();
        }

        const updated = await updateLLMProvider(editingProvider.id, payload);
        setProviders((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
        setSuccessBanner(`Successfully updated provider "${updated.name}".`);
        handleCloseModal();
      }
    } catch (err: any) {
      setModalError(err.message || 'Failed to save provider.');
    } finally {
      setIsSavingProvider(false);
      setFormApiKey(''); // Secret hygiene: wipe key state immediately after save
    }
  };

  // Confirm Clear Key
  const handleConfirmClearKey = async () => {
    if (!clearKeyModalProvider) return;
    setIsClearingKey(true);
    setErrorBanner(null);

    try {
      const updated = await updateLLMProvider(clearKeyModalProvider.id, { clear_api_key: true });
      setProviders((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      setSuccessBanner(`API key removed from provider "${updated.name}".`);
      setClearKeyModalProvider(null);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to remove API key.');
      setClearKeyModalProvider(null);
    } finally {
      setIsClearingKey(false);
    }
  };

  // Confirm Delete Provider
  const handleConfirmDelete = async () => {
    if (!deleteModalProvider) return;
    setIsDeletingProvider(true);
    setDeleteError(null);

    try {
      await deleteLLMProvider(deleteModalProvider.id);
      setProviders((prev) => prev.filter((p) => p.id !== deleteModalProvider.id));
      setSuccessBanner(`Provider "${deleteModalProvider.name}" deleted successfully.`);
      setDeleteModalProvider(null);
    } catch (err: any) {
      setDeleteError(err.message || 'Failed to delete provider.');
    } finally {
      setIsDeletingProvider(false);
    }
  };

  // Format timestamp helper
  const formatTime = (isoString?: string | null) => {
    if (!isoString) return 'Never tested';
    try {
      const d = new Date(isoString);
      return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoString;
    }
  };

  if (!user || user.role !== 'admin') {
    return (
      <div className="p-8 glass-panel rounded-2xl border border-red-500/20 text-center space-y-4 max-w-md mx-auto my-12 animate-fade-in">
        <div className="w-12 h-12 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-center justify-center mx-auto">
          <ShieldAlert className="w-6 h-6" />
        </div>
        <h3 className="text-base font-bold text-white">Administrator Privileges Required</h3>
        <p className="text-xs text-gray-400 leading-relaxed">
          You must be signed in with an administrator account to view or modify LLM provider and API key settings.
        </p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-emerald-400 gap-3">
        <Loader2 className="w-8 h-8 animate-spin" />
        <p className="text-xs text-gray-400">Loading LLM configuration and providers...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Toast / Notification Banners */}
      {successBanner && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 flex items-center justify-between text-xs animate-fade-in shadow-lg">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successBanner}</span>
          </div>
          <button onClick={() => setSuccessBanner(null)} className="p-1 hover:text-white">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {errorBanner && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 flex items-center justify-between text-xs animate-fade-in shadow-lg">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
            <span>{errorBanner}</span>
          </div>
          <button onClick={() => setErrorBanner(null)} className="p-1 hover:text-white">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Warning Alert Banner (if unconfigured, disabled, or failed test) */}
      {hasWarning && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 flex items-start gap-3 text-xs animate-fade-in shadow-md">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-semibold text-white">Attention: Active LLM Provider Warning</p>
            <p className="text-amber-200/80 leading-relaxed">
              {!providers || providers.length === 0
                ? 'No LLM providers are registered. Please add a provider below to enable chat answer generation.'
                : !activeProvider
                ? 'No active provider is currently selected in LLM Settings. Chat answer generation is suspended.'
                : activeProvider.is_enabled === false
                ? `Active provider "${activeProvider.name}" is disabled. Chat answer generation will fail or use fallback.`
                : activeProvider.last_test_status === 'failed'
                ? `Active provider "${activeProvider.name}" failed its most recent connection test. Please verify the API key and endpoint URL.`
                : 'Please verify LLM provider configuration.'}
            </p>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------------------- */}
      {/* SECTION 1: Active Model & Generation Settings Card                      */}
      {/* ---------------------------------------------------------------------- */}
      <div className="glass-panel p-6 rounded-2xl border border-gray-800 shadow-xl space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-gray-800/80 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center">
              <SlidersHorizontal className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <span>Active Model & Generation Parameters</span>
                {settings && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                    v{settings.version}
                  </span>
                )}
              </h2>
              <p className="text-[11px] text-gray-400">
                Configure primary answer model, failover recovery, and sampling parameters.
              </p>
            </div>
          </div>

          <button
            onClick={handleSaveSettings}
            disabled={!isSettingsModified || !isSettingsValid || isSavingSettings}
            className={`px-4 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all shadow-md ${
              isSettingsModified && isSettingsValid
                ? 'bg-emerald-500 hover:bg-emerald-400 text-gray-950 font-bold shadow-emerald-500/20'
                : 'bg-gray-800 text-gray-500 cursor-not-allowed border border-gray-700/50'
            }`}
          >
            {isSavingSettings ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Applying...</span>
              </>
            ) : (
              <>
                <Check className="w-3.5 h-3.5" />
                <span>Save & Hot Reload</span>
              </>
            )}
          </button>
        </div>

        {/* Runtime Settings Controls Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Active Provider & Model Column */}
          <div className="space-y-4 p-4 rounded-xl bg-gray-900/60 border border-gray-800/60">
            <h3 className="text-xs font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Primary Answer Provider</span>
            </h3>

            <div className="space-y-1.5">
              <label className="text-[11px] font-medium text-gray-300">Active Provider</label>
              <select
                value={selectedActiveProviderId}
                onChange={(e) => setSelectedActiveProviderId(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-800 text-xs text-white focus:outline-none focus:border-emerald-500"
              >
                {providers
                  .filter((p) => p.is_enabled ?? true)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.provider_type})
                    </option>
                  ))}
              </select>
            </div>

            <div className="space-y-1.5">
              <label className="text-[11px] font-medium text-gray-300">Active Model</label>
              <select
                value={selectedActiveModel}
                onChange={(e) => setSelectedActiveModel(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-800 text-xs text-white focus:outline-none focus:border-emerald-500"
              >
                {activeProviderModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Fallback Provider & Model Column */}
          <div className="space-y-4 p-4 rounded-xl bg-gray-900/60 border border-gray-800/60">
            <h3 className="text-xs font-bold text-gray-300 uppercase tracking-wider flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-gray-400" />
              <span>Fallback Provider (Optional)</span>
            </h3>

            <div className="space-y-1.5">
              <label className="text-[11px] font-medium text-gray-300">Fallback Provider</label>
              <select
                value={selectedFallbackProviderId}
                onChange={(e) => setSelectedFallbackProviderId(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-800 text-xs text-white focus:outline-none focus:border-emerald-500"
              >
                <option value="none">None (No automatic failover)</option>
                {providers
                  .filter((p) => (p.is_enabled ?? true) && p.id !== selectedActiveProviderId)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.provider_type})
                    </option>
                  ))}
              </select>
            </div>

            {selectedFallbackProviderId !== 'none' && (
              <div className="space-y-1.5">
                <label className="text-[11px] font-medium text-gray-300">Fallback Model</label>
                <select
                  value={selectedFallbackModel}
                  onChange={(e) => setSelectedFallbackModel(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-800 text-xs text-white focus:outline-none focus:border-emerald-500"
                >
                  {fallbackProviderModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        {/* Sampling Parameters (Temperature & Max Tokens) */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 p-4 rounded-xl bg-gray-900/40 border border-gray-800/40">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px]">
              <label className="font-medium text-gray-300">Temperature</label>
              <span className="font-mono text-emerald-400 font-bold">{temperature.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min="0.0"
              max="2.0"
              step="0.05"
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value))}
              className="w-full accent-emerald-500 cursor-pointer"
            />
            <p className="text-[10px] text-gray-400">0.0 = deterministic and focused; 1.0+ = creative sampling.</p>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px]">
              <label className="font-medium text-gray-300">Max Tokens</label>
              <span className="font-mono text-emerald-400 font-bold">{maxTokens}</span>
            </div>
            <input
              type="number"
              min="64"
              max="8192"
              step="64"
              value={maxTokens}
              onChange={(e) => setMaxTokens(parseInt(e.target.value, 10) || 1024)}
              className="w-full px-3 py-1.5 rounded-lg bg-gray-950 border border-gray-800 text-xs text-white focus:outline-none focus:border-emerald-500 font-mono"
            />
            <p className="text-[10px] text-gray-400">Maximum response length generation boundary (1 to 8192).</p>
          </div>
        </div>

        {/* In-Flight Stream Isolation Notice */}
        <div className="p-3 rounded-xl bg-emerald-500/5 border border-emerald-500/20 text-emerald-300/80 text-[11px] flex items-center gap-2">
          <Info className="w-4 h-4 text-emerald-400 shrink-0" />
          <span>
            Changes apply immediately to new chats via Redis hot-reload. In-flight streams complete using the model
            they started with.
          </span>
        </div>
      </div>

      {/* ---------------------------------------------------------------------- */}
      {/* SECTION 2: Provider List & Management Card                             */}
      {/* ---------------------------------------------------------------------- */}
      <div className="glass-panel p-6 rounded-2xl border border-gray-800 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-gray-800/80 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center">
              <Server className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <span>LLM Providers</span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-800 text-gray-400">
                  {providers.length} registered
                </span>
              </h2>
              <p className="text-[11px] text-gray-400">
                Manage registered endpoints, API keys, and connection credentials.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => loadData(true)}
              disabled={isRefreshing}
              className="p-2 rounded-xl bg-gray-900 hover:bg-gray-800 text-gray-400 hover:text-white border border-gray-800 transition-colors"
              title="Refresh Providers"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-emerald-400' : ''}`} />
            </button>

            <button
              onClick={handleOpenCreateModal}
              className="px-3.5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-gray-950 font-bold text-xs flex items-center gap-1.5 transition-all shadow-md shadow-emerald-500/20"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Add Provider</span>
            </button>
          </div>
        </div>

        {/* Providers Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-gray-300">
            <thead className="bg-gray-900/60 text-[10px] uppercase font-bold text-gray-400 border-b border-gray-800 tracking-wider">
              <tr>
                <th className="py-3 px-3">Provider Name</th>
                <th className="py-3 px-3">Type</th>
                <th className="py-3 px-3">Base URL</th>
                <th className="py-3 px-3">Key Status</th>
                <th className="py-3 px-3">Models</th>
                <th className="py-3 px-3">Last Test</th>
                <th className="py-3 px-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {providers.map((p) => {
                const isActive = settings?.active_provider_id === p.id;
                const isFallback = settings?.fallback_provider_id === p.id;

                return (
                  <tr key={p.id} className="hover:bg-gray-900/30 transition-colors">
                    <td className="py-3.5 px-3">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-white">{p.name}</span>
                        {isActive && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 uppercase">
                            Active
                          </span>
                        )}
                        {isFallback && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30 uppercase">
                            Fallback
                          </span>
                        )}
                        {!p.is_enabled && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-gray-800 text-gray-400 uppercase">
                            Disabled
                          </span>
                        )}
                      </div>
                    </td>

                    <td className="py-3.5 px-3">
                      <span className="px-2 py-0.5 rounded-md bg-gray-900 text-gray-300 font-mono text-[10px] border border-gray-800">
                        {p.provider_type}
                      </span>
                    </td>

                    <td className="py-3.5 px-3 font-mono text-[11px] text-gray-400 max-w-[200px] truncate" title={p.base_url}>
                      {p.base_url}
                    </td>

                    <td className="py-3.5 px-3">
                      {(p.has_api_key ?? p.has_key) ? (
                        <div className="flex items-center gap-1.5 text-emerald-400 font-mono text-[11px]">
                          <Key className="w-3 h-3 text-emerald-400" />
                          <span>{p.api_key_masked_hint ?? p.key_hint ?? 'Configured'}</span>
                        </div>
                      ) : (
                        <span className="text-gray-500 text-[11px] italic">No key</span>
                      )}
                    </td>

                    <td className="py-3.5 px-3">
                      <div className="flex flex-wrap gap-1 max-w-[180px]">
                        {p.models && Array.isArray(p.models) && p.models.length > 0 ? (
                          <>
                            {p.models.slice(0, 2).map((m) => (
                              <span key={m} className="px-1.5 py-0.5 rounded bg-gray-900 text-gray-300 font-mono text-[10px]">
                                {m}
                              </span>
                            ))}
                            {p.models.length > 2 && (
                              <span className="text-[10px] text-gray-500">+{p.models.length - 2} more</span>
                            )}
                          </>
                        ) : (
                          <span className="text-gray-300 font-mono text-[11px]">{p.default_model}</span>
                        )}
                      </div>
                    </td>

                    <td className="py-3.5 px-3">
                      {p.last_test_status === 'success' ? (
                        <span className="inline-flex items-center gap-1 text-emerald-400 text-[10px] font-medium" title={p.last_test_at || ''}>
                          <CheckCircle2 className="w-3 h-3" />
                          <span>OK ({formatTime(p.last_test_at)})</span>
                        </span>
                      ) : p.last_test_status === 'failed' ? (
                        <span className="inline-flex items-center gap-1 text-red-400 text-[10px] font-medium" title={p.last_test_at || ''}>
                          <XCircle className="w-3 h-3" />
                          <span>Failed ({formatTime(p.last_test_at)})</span>
                        </span>
                      ) : (
                        <span className="text-gray-500 text-[10px]">Never tested</span>
                      )}
                    </td>

                    <td className="py-3.5 px-3 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => handleTestConnection(p)}
                          disabled={testingId === p.id}
                          className="p-1.5 rounded-lg bg-gray-900 hover:bg-gray-800 text-gray-300 hover:text-emerald-400 transition-colors border border-gray-800"
                          title="Test Connection"
                        >
                          {testingId === p.id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-400" />
                          ) : (
                            <RefreshCw className="w-3.5 h-3.5" />
                          )}
                        </button>

                        <button
                          onClick={() => handleOpenEditModal(p)}
                          className="p-1.5 rounded-lg bg-gray-900 hover:bg-gray-800 text-gray-300 hover:text-white transition-colors border border-gray-800"
                          title="Edit Provider"
                        >
                          <Edit className="w-3.5 h-3.5" />
                        </button>

                        <button
                          onClick={() => {
                            setDeleteError(null);
                            setDeleteModalProvider(p);
                          }}
                          className="p-1.5 rounded-lg bg-gray-900 hover:bg-red-500/10 text-gray-400 hover:text-red-400 transition-colors border border-gray-800"
                          title="Delete Provider"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---------------------------------------------------------------------- */}
      {/* SECTION 3: Read-Only System Models Card (Embedding & Reranker)         */}
      {/* ---------------------------------------------------------------------- */}
      <div className="glass-panel p-6 rounded-2xl border border-gray-800 shadow-xl space-y-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center">
            <Layers className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white flex items-center gap-2">
              <span>Vector Ingestion & Reranking Architecture</span>
              <span className="text-[10px] px-2 py-0.5 rounded-md bg-gray-900 text-gray-400 border border-gray-800 uppercase">
                Read-Only
              </span>
            </h2>
            <p className="text-[11px] text-gray-400">
              System embedding and cross-encoder models configured in environment.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
          <div className="p-4 rounded-xl bg-gray-900/40 border border-gray-800/60 space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Dense & Sparse Embeddings</span>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm text-emerald-400 font-semibold">
                {health?.embedding_model || 'BAAI/bge-m3'}
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 font-medium">
                {health?.embedding_status || 'Ready'}
              </span>
            </div>
            <p className="text-[10px] text-gray-400">
              Dual FastEmbed vectors (1024-dim dense + BM25 sparse) stored in Qdrant collection.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-gray-900/40 border border-gray-800/60 space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Cross-Encoder Reranker</span>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm text-emerald-400 font-semibold">
                {health?.reranker_model || 'BAAI/bge-reranker-v2-m3'}
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 font-medium">
                {health?.reranker_status || 'Configured'}
              </span>
            </div>
            <p className="text-[10px] text-gray-400">
              FastEmbed cross-encoder singleton computing calibrated sigmoid relevance scores.
            </p>
          </div>
        </div>

        <p className="text-[10px] text-gray-500 italic pt-1">
          * Note: Embedding and reranker models cannot be changed at runtime because vector collections depend on fixed dimensional embeddings. Modifying them requires re-indexing all knowledge base documents.
        </p>
      </div>

      {/* ---------------------------------------------------------------------- */}
      {/* MODAL 1: Add / Edit Provider Modal                                     */}
      {/* ---------------------------------------------------------------------- */}
      {modalMode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-lg glass-panel p-6 rounded-2xl border border-gray-700 shadow-2xl space-y-5 text-left">
            <div className="flex items-center justify-between border-b border-gray-800 pb-3">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Cpu className="w-4 h-4 text-emerald-400" />
                <span>{modalMode === 'create' ? 'Add LLM Provider' : `Edit "${editingProvider?.name}"`}</span>
              </h3>
              <button onClick={handleCloseModal} className="p-1 rounded-lg text-gray-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>

            {modalError && (
              <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                <span>{modalError}</span>
              </div>
            )}

            <form onSubmit={handleSubmitProvider} className="space-y-4 text-xs">
              {/* Preset Selector */}
              {modalMode === 'create' && (
                <div className="space-y-1.5">
                  <label className="font-semibold text-gray-300">Provider Preset</label>
                  <select
                    value={selectedPreset}
                    onChange={(e) => handlePresetChange(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-gray-900 border border-gray-800 text-white focus:outline-none focus:border-emerald-500"
                  >
                    {Object.entries(PRESETS).map(([key, cfg]) => (
                      <option key={key} value={key}>
                        {cfg.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Provider Name */}
              <div className="space-y-1.5">
                <label className="font-semibold text-gray-300">Provider Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. OpenAI Production"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-gray-900 border border-gray-800 text-white focus:outline-none focus:border-emerald-500"
                />
              </div>

              {/* Base URL */}
              <div className="space-y-1.5">
                <label className="font-semibold text-gray-300">Base URL</label>
                <input
                  type="url"
                  required
                  placeholder="https://api.openai.com/v1"
                  value={formBaseUrl}
                  onChange={(e) => setFormBaseUrl(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-gray-900 border border-gray-800 text-white font-mono text-xs focus:outline-none focus:border-emerald-500"
                />
                {selectedPreset === 'ollama' && (
                  <p className="text-[10px] text-amber-300/80">
                    Local/loopback URLs require <code className="text-amber-200">ALLOW_PRIVATE_LLM_URLS=true</code> in dev.
                  </p>
                )}
              </div>

              {/* API Key (Strict Secret Hygiene) */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="font-semibold text-gray-300">
                    API Key {selectedPreset === 'ollama' ? '(Optional)' : ''}
                  </label>
                  {modalMode === 'edit' && (editingProvider?.has_api_key ?? editingProvider?.has_key) && (
                    <button
                      type="button"
                      onClick={() => {
                        handleCloseModal();
                        setClearKeyModalProvider(editingProvider);
                      }}
                      className="text-[11px] text-red-400 hover:text-red-300 underline font-medium"
                    >
                      Clear Key
                    </button>
                  )}
                </div>
                {modalMode === 'edit' && (editingProvider?.has_api_key ?? editingProvider?.has_key) && (
                  <div className="text-[11px] text-emerald-400 font-mono flex items-center gap-1.5">
                    <Key className="w-3 h-3" />
                    <span>
                      Key configured: {editingProvider.api_key_masked_hint ?? editingProvider.key_hint ?? '••••'}
                    </span>
                  </div>
                )}
                <input
                  type="password"
                  autoComplete="new-password"
                  placeholder={
                    modalMode === 'edit' && (editingProvider?.has_api_key ?? editingProvider?.has_key)
                      ? 'Leave empty to keep existing key'
                      : 'Enter API key'
                  }
                  value={formApiKey}
                  onChange={(e) => setFormApiKey(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-gray-900 border border-gray-800 text-white font-mono text-xs focus:outline-none focus:border-emerald-500"
                />
                <p className="text-[10px] text-gray-500">
                  Key is encrypted with Fernet at rest. Never stored in local storage, logs, or echoed back.
                </p>
              </div>

              {/* Models List */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="font-semibold text-gray-300">Supported Models (comma-separated)</label>
                  {modalMode === 'edit' && editingProvider && (
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          const res = await fetchLLMModels(editingProvider.id);
                          if (res.models && res.models.length > 0) {
                            setFormModelsText(res.models.join(', '));
                            if (!res.models.includes(formDefaultModel)) {
                              setFormDefaultModel(res.models[0]);
                            }
                          }
                        } catch (e: any) {
                          setModalError(e.message || 'Failed to fetch models from provider');
                        }
                      }}
                      className="text-[11px] text-emerald-400 hover:text-emerald-300 underline font-medium"
                    >
                      Fetch Models
                    </button>
                  )}
                </div>
                <input
                  type="text"
                  required
                  placeholder="gpt-4o, gpt-4o-mini"
                  value={formModelsText}
                  onChange={(e) => setFormModelsText(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-gray-900 border border-gray-800 text-white font-mono text-xs focus:outline-none focus:border-emerald-500"
                />
              </div>

              {/* Default Model */}
              <div className="space-y-1.5">
                <label className="font-semibold text-gray-300">Default Model</label>
                <input
                  type="text"
                  required
                  placeholder="gpt-4o"
                  value={formDefaultModel}
                  onChange={(e) => setFormDefaultModel(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-gray-900 border border-gray-800 text-white font-mono text-xs focus:outline-none focus:border-emerald-500"
                />
              </div>

              {/* Enabled Switch */}
              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="isEnabledCheckbox"
                  checked={formIsEnabled}
                  onChange={(e) => setFormIsEnabled(e.target.checked)}
                  className="rounded bg-gray-900 border-gray-800 text-emerald-500 focus:ring-0 cursor-pointer"
                />
                <label htmlFor="isEnabledCheckbox" className="text-gray-300 cursor-pointer font-medium">
                  Enable this provider
                </label>
              </div>

              {/* Modal Action Buttons */}
              <div className="flex items-center justify-end gap-2 pt-4 border-t border-gray-800">
                <button
                  type="button"
                  onClick={handleCloseModal}
                  className="px-4 py-2 rounded-xl bg-gray-900 hover:bg-gray-800 text-gray-300 text-xs font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSavingProvider}
                  className="px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-gray-950 text-xs font-bold flex items-center gap-1.5"
                >
                  {isSavingProvider ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                  <span>Save Provider</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------------------- */}
      {/* MODAL 2: Test Result Modal                                             */}
      {/* ---------------------------------------------------------------------- */}
      {testResultModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-md glass-panel p-6 rounded-2xl border border-gray-700 shadow-2xl space-y-4 text-left">
            <div className="flex items-center gap-3">
              <div
                className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                  testResultModal.success
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : 'bg-red-500/10 text-red-400 border border-red-500/20'
                }`}
              >
                {testResultModal.success ? <CheckCircle2 className="w-5 h-5" /> : <XCircle className="w-5 h-5" />}
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Connection Test: {testResultModal.providerName}</h3>
                <span
                  className={`text-[10px] font-bold uppercase tracking-wider ${
                    testResultModal.success ? 'text-emerald-400' : 'text-red-400'
                  }`}
                >
                  {testResultModal.success ? 'Connection Successful' : 'Connection Failed'}
                </span>
              </div>
            </div>

            <p className="text-xs text-gray-300 leading-relaxed">{testResultModal.message}</p>

            {testResultModal.sanitizedError && (
              <div className="p-3 rounded-xl bg-gray-900 border border-gray-800 text-red-300 text-[11px] font-mono whitespace-pre-wrap max-h-40 overflow-y-auto">
                {testResultModal.sanitizedError}
              </div>
            )}

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setTestResultModal(null)}
                className="px-4 py-2 rounded-xl bg-gray-800 hover:bg-gray-700 text-white text-xs font-semibold"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------------------- */}
      {/* MODAL 3: Remove Key Confirmation Modal                                  */}
      {/* ---------------------------------------------------------------------- */}
      {clearKeyModalProvider && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-md glass-panel p-6 rounded-2xl border border-gray-700 shadow-2xl space-y-4 text-left">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-center justify-center">
                <Key className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Remove API Key?</h3>
                <p className="text-xs text-gray-400">{clearKeyModalProvider.name}</p>
              </div>
            </div>

            <p className="text-xs text-gray-300 leading-relaxed">
              Are you sure you want to remove the stored API key for this provider?
              {settings?.active_provider_id === clearKeyModalProvider.id && (
                <span className="block mt-2 font-semibold text-red-400">
                  Warning: This provider is currently active in LLM settings. Removing its key will cause chat requests to fail or be rejected.
                </span>
              )}
            </p>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setClearKeyModalProvider(null)}
                className="px-4 py-2 rounded-xl bg-gray-900 hover:bg-gray-800 text-gray-300 text-xs font-semibold"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmClearKey}
                disabled={isClearingKey}
                className="px-4 py-2 rounded-xl bg-red-500 hover:bg-red-400 text-white text-xs font-bold flex items-center gap-1.5"
              >
                {isClearingKey ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                <span>Yes, Clear Key</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------------------- */}
      {/* MODAL 4: Delete Provider Confirmation Modal                             */}
      {/* ---------------------------------------------------------------------- */}
      {deleteModalProvider && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-md glass-panel p-6 rounded-2xl border border-gray-700 shadow-2xl space-y-4 text-left">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-center justify-center">
                <Trash2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Delete Provider?</h3>
                <p className="text-xs text-gray-400">{deleteModalProvider.name}</p>
              </div>
            </div>

            {deleteError && (
              <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                <span>{deleteError}</span>
              </div>
            )}

            <p className="text-xs text-gray-300 leading-relaxed">
              Are you sure you want to permanently delete this provider configuration?
              {settings?.active_provider_id === deleteModalProvider.id && (
                <span className="block mt-2 font-semibold text-red-400">
                  This provider is currently active in LLM settings. Deletion will be blocked (HTTP 409).
                </span>
              )}
            </p>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setDeleteModalProvider(null)}
                className="px-4 py-2 rounded-xl bg-gray-900 hover:bg-gray-800 text-gray-300 text-xs font-semibold"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                disabled={isDeletingProvider}
                className="px-4 py-2 rounded-xl bg-red-500 hover:bg-red-400 text-white text-xs font-bold flex items-center gap-1.5"
              >
                {isDeletingProvider ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                <span>Delete Permanently</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
