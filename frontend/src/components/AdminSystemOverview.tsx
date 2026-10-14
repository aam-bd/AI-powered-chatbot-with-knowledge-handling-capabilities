'use client';

import React, { useState, useEffect } from 'react';
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
import {
  fetchSystemHealth,
  fetchSystemRoutes,
  fetchVectorStoreStats,
  fetchArchitectureOverview,
  fetchWorkerStats,
  fetchChatQualityIndicators,
  fetchRecentActivity,
  fetchSystemSettings,
  updateSystemSettings,
  resetSystemSettings,
  fetchSystemEnvironment,
} from '@/services/api';

export default function AdminSystemOverview() {
  // Data states
  const [health, setHealth] = useState<AdminSystemHealthResponse | null>(null);
  const [routesData, setRoutesData] = useState<SystemRoutesResponse | null>(null);
  const [vectorStats, setVectorStats] = useState<VectorStoreStatsResponse | null>(null);
  const [architecture, setArchitecture] = useState<ArchitectureOverviewResponse | null>(null);
  const [workers, setWorkers] = useState<WorkerStatsResponse | null>(null);
  const [quality, setQuality] = useState<ChatQualityIndicatorsResponse | null>(null);
  const [activity, setActivity] = useState<RecentActivityResponse | null>(null);
  const [settings, setSettings] = useState<SystemSettingsResponse | null>(null);
  const [environment, setEnvironment] = useState<SystemEnvironmentResponse | null>(null);

  // UI & Form states
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [qualityWindow, setQualityWindow] = useState<'24h' | '7d'>('24h');
  const [routeSearch, setRouteSearch] = useState<string>('');
  const [savingSettings, setSavingSettings] = useState<boolean>(false);
  const [showResetConfirm, setShowResetConfirm] = useState<boolean>(false);

  // Settings form values
  const [formThreshold, setFormThreshold] = useState<number>(0.5);
  const [formTopK, setFormTopK] = useState<number>(15);
  const [formTopN, setFormTopN] = useState<number>(4);
  const [formHistory, setFormHistory] = useState<number>(6);
  const [formRateLimit, setFormRateLimit] = useState<number>(60);
  const [formRateLimitLogin, setFormRateLimitLogin] = useState<number>(5);
  const [formKeepalive, setFormKeepalive] = useState<number>(15);
  const [formMaxUploadMB, setFormMaxUploadMB] = useState<number>(20);

  const loadAllData = async (isInitial = false) => {
    if (isInitial) setLoading(true);
    else setRefreshing(true);
    setError(null);

    try {
      const [
        hRes,
        rRes,
        vRes,
        aRes,
        wRes,
        qRes,
        actRes,
        sRes,
        eRes,
      ] = await Promise.all([
        fetchSystemHealth(),
        fetchSystemRoutes(),
        fetchVectorStoreStats(),
        fetchArchitectureOverview(),
        fetchWorkerStats(),
        fetchChatQualityIndicators(qualityWindow),
        fetchRecentActivity(),
        fetchSystemSettings(),
        fetchSystemEnvironment(),
      ]);

      setHealth(hRes);
      setRoutesData(rRes);
      setVectorStats(vRes);
      setArchitecture(aRes);
      setWorkers(wRes);
      setQuality(qRes);
      setActivity(actRes);
      setSettings(sRes);
      setEnvironment(eRes);

      // Populate settings form
      if (sRes) {
        setFormThreshold(sRes.reranker_threshold);
        setFormTopK(sRes.retrieval_top_k);
        setFormTopN(sRes.rerank_top_n);
        setFormHistory(sRes.history_messages);
        setFormRateLimit(sRes.rate_limit_per_minute);
        setFormRateLimitLogin(sRes.rate_limit_login_per_minute);
        setFormKeepalive(sRes.sse_keepalive_interval);
        setFormMaxUploadMB(Math.round(sRes.max_upload_size_bytes / (1024 * 1024)));
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load system overview details');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadAllData(true);
  }, []);

  // Reload quality metrics on window change
  useEffect(() => {
    fetchChatQualityIndicators(qualityWindow)
      .then((q) => setQuality(q))
      .catch((err) => console.error('Failed to update quality metrics:', err));
  }, [qualityWindow]);

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    if (formTopN > formTopK) {
      setError('Rerank Top N cannot exceed Retrieval Top K.');
      return;
    }

    setSavingSettings(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const updated = await updateSystemSettings({
        reranker_threshold: formThreshold,
        retrieval_top_k: formTopK,
        rerank_top_n: formTopN,
        history_messages: formHistory,
        rate_limit_per_minute: formRateLimit,
        rate_limit_login_per_minute: formRateLimitLogin,
        sse_keepalive_interval: formKeepalive,
        max_upload_size_bytes: formMaxUploadMB * 1024 * 1024,
      });

      setSettings(updated);
      setSuccessMessage(
        `System settings updated successfully to version v${updated.version}. Hot-reloaded to all active workers.`
      );
      // Refresh architecture and activity
      const [newArch, newAct] = await Promise.all([
        fetchArchitectureOverview(),
        fetchRecentActivity(),
      ]);
      setArchitecture(newArch);
      setActivity(newAct);
    } catch (err: any) {
      setError(err.message || 'Failed to update system settings');
    } finally {
      setSavingSettings(false);
    }
  };

  const handleResetSettings = async () => {
    setShowResetConfirm(false);
    setSavingSettings(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const reset = await resetSystemSettings();
      setSettings(reset);
      setFormThreshold(reset.reranker_threshold);
      setFormTopK(reset.retrieval_top_k);
      setFormTopN(reset.rerank_top_n);
      setFormHistory(reset.history_messages);
      setFormRateLimit(reset.rate_limit_per_minute);
      setFormRateLimitLogin(reset.rate_limit_login_per_minute);
      setFormKeepalive(reset.sse_keepalive_interval);
      setFormMaxUploadMB(Math.round(reset.max_upload_size_bytes / (1024 * 1024)));

      setSuccessMessage(`System settings reset to baseline defaults (v${reset.version}).`);
      const [newArch, newAct] = await Promise.all([
        fetchArchitectureOverview(),
        fetchRecentActivity(),
      ]);
      setArchitecture(newArch);
      setActivity(newAct);
    } catch (err: any) {
      setError(err.message || 'Failed to reset system settings');
    } finally {
      setSavingSettings(false);
    }
  };

  const filteredRoutes = routesData?.routes.filter((r) =>
    r.path.toLowerCase().includes(routeSearch.toLowerCase()) ||
    r.method.toLowerCase().includes(routeSearch.toLowerCase()) ||
    (r.summary && r.summary.toLowerCase().includes(routeSearch.toLowerCase())) ||
    r.tags.some((t) => t.toLowerCase().includes(routeSearch.toLowerCase()))
  ) || [];

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center p-16 space-y-4">
        <div className="w-10 h-10 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
        <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
          Gathering live system telemetry & service health...
        </p>
      </div>
    );
  }

  const isGroundingWarning = formThreshold < 0.5;

  return (
    <div className="space-y-8">
      {/* Header & Quick Action */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white flex items-center gap-2">
            <span>System Overview & Control</span>
            {health && (
              <span
                className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider ${
                  health.status === 'healthy'
                    ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                    : health.status === 'degraded'
                    ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
                    : 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300'
                }`}
              >
                <span
                  className={`w-2 h-2 mr-1.5 rounded-full ${
                    health.status === 'healthy'
                      ? 'bg-emerald-500'
                      : health.status === 'degraded'
                      ? 'bg-amber-500'
                      : 'bg-rose-500'
                  }`}
                />
                {health.status}
              </span>
            )}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Real-time infrastructure health, dynamic parameters, vector store sync, and runtime guardrails.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {health && (
            <span className="text-xs text-slate-400">
              Checked: {new Date(health.checked_at).toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => loadAllData(false)}
            disabled={refreshing}
            className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700/80 border border-slate-300 dark:border-slate-700 rounded-lg shadow-sm transition"
          >
            <svg
              className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            Refresh Telemetry
          </button>
        </div>
      </div>

      {/* Global Alerts */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200 text-sm flex items-start gap-3">
          <svg className="w-5 h-5 text-rose-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clipRule="evenodd"
            />
          </svg>
          <div>
            <p className="font-semibold">Notice</p>
            <p className="mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {successMessage && (
        <div className="p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-200 text-sm flex items-start gap-3">
          <svg className="w-5 h-5 text-emerald-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
              clipRule="evenodd"
            />
          </svg>
          <div>
            <p className="font-semibold">Success</p>
            <p className="mt-0.5">{successMessage}</p>
          </div>
        </div>
      )}

      {/* SECTION 1: Service Health & Per-Dependency Latencies */}
      <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm">
        <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-4 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Service Dependencies & Live Round-Trip Latency
          </span>
          <span className="text-xs text-slate-400 font-normal">Active Ping</span>
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {health &&
            Object.entries(health.dependencies).map(([key, item]) => {
              const isHealthy = item.status === 'healthy';
              const isDegraded = item.status === 'degraded';
              return (
                <div
                  key={key}
                  className="p-4 rounded-xl border border-slate-100 dark:border-slate-800/80 bg-slate-50/50 dark:bg-slate-800/40 flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                        {item.name}
                      </span>
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                          isHealthy
                            ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                            : isDegraded
                            ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
                            : 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300'
                        }`}
                      >
                        {item.status}
                      </span>
                    </div>

                    <div className="text-2xl font-bold text-slate-900 dark:text-white flex items-baseline gap-1">
                      {item.latency_ms !== null && item.latency_ms !== undefined ? (
                        <>
                          <span>{item.latency_ms}</span>
                          <span className="text-xs font-normal text-slate-500">ms</span>
                        </>
                      ) : (
                        <span className="text-xs text-slate-400">N/A</span>
                      )}
                    </div>
                  </div>

                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-2 truncate" title={item.message || ''}>
                    {item.message || 'Operational'}
                  </p>
                </div>
              );
            })}
        </div>
      </section>

      {/* SECTION 2: Runtime Settings Editor (The Control Hub) */}
      <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4 pb-3 border-b border-slate-100 dark:border-slate-800">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
              <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
              </svg>
              Runtime Editable Settings (Hot-Reloaded)
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Changes update immediately in PostgreSQL and Redis without requiring server restarts. Current: v{settings?.version || 1}
            </p>
          </div>

          <button
            type="button"
            onClick={() => setShowResetConfirm(true)}
            className="text-xs font-medium text-rose-600 dark:text-rose-400 hover:text-rose-700 underline"
          >
            Reset to Environment Defaults
          </button>
        </div>

        {/* Warning Banner if threshold is lowered below 0.50 */}
        {isGroundingWarning && (
          <div className="mb-6 p-4 rounded-xl bg-amber-50 dark:bg-amber-950/50 border border-amber-300 dark:border-amber-700/80 text-amber-900 dark:text-amber-200 text-xs sm:text-sm flex items-start gap-3">
            <svg className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
                clipRule="evenodd"
              />
            </svg>
            <div>
              <p className="font-bold">⚠️ Grounding Guardrail Alert</p>
              <p className="mt-0.5 leading-relaxed">
                Reranker threshold is set to <strong>{formThreshold.toFixed(2)}</strong> (below standard 0.50).
                Lowering the threshold admits weaker semantic matches, which weakens Layer 1 grounding and increases
                the probability of hallucinations or ungrounded responses. An audit record will be logged.
              </p>
            </div>
          </div>
        )}

        <form onSubmit={handleSaveSettings} className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {/* Reranker Threshold */}
            <div>
              <label htmlFor="setting-threshold" className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Reranker Threshold (0.20 - 0.95)
              </label>
              <input
                id="setting-threshold"
                type="number"
                step="0.05"
                min="0.20"
                max="0.95"
                value={formThreshold}
                onChange={(e) => setFormThreshold(parseFloat(e.target.value) || 0.5)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-1 block">Layer 1 cutoff score</span>
            </div>

            {/* Retrieval Top K */}
            <div>
              <label htmlFor="setting-top-k" className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Retrieval Top K (5 - 50)
              </label>
              <input
                id="setting-top-k"
                type="number"
                min="5"
                max="50"
                value={formTopK}
                onChange={(e) => setFormTopK(parseInt(e.target.value) || 15)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-1 block">Candidates from hybrid search</span>
            </div>

            {/* Rerank Top N */}
            <div>
              <label htmlFor="setting-top-n" className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Rerank Top N (1 - 10)
              </label>
              <input
                id="setting-top-n"
                type="number"
                min="1"
                max="10"
                value={formTopN}
                onChange={(e) => setFormTopN(parseInt(e.target.value) || 4)}
                className={`w-full px-3 py-2 text-sm rounded-lg border ${
                  formTopN > formTopK
                    ? 'border-rose-500 ring-1 ring-rose-500'
                    : 'border-slate-300 dark:border-slate-700'
                } bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500`}
              />
              {formTopN > formTopK ? (
                <span className="text-[11px] text-rose-500 font-semibold mt-1 block">
                  Rerank Top N cannot exceed Retrieval Top K
                </span>
              ) : (
                <span className="text-[11px] text-slate-400 mt-1 block">Context chunks fed to prompt</span>
              )}
            </div>

            {/* History Window */}
            <div>
              <label htmlFor="setting-history" className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                History Messages (0 - 20)
              </label>
              <input
                id="setting-history"
                type="number"
                min="0"
                max="20"
                value={formHistory}
                onChange={(e) => setFormHistory(parseInt(e.target.value) || 6)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-1 block">Sliding context window length</span>
            </div>

            {/* Rate Limit Per Minute */}
            <div>
              <label htmlFor="setting-rate-limit" className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                API Rate Limit (req/min)
              </label>
              <input
                id="setting-rate-limit"
                type="number"
                min="10"
                max="300"
                value={formRateLimit}
                onChange={(e) => setFormRateLimit(parseInt(e.target.value) || 60)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-1 block">General IP throttle limit</span>
            </div>

            {/* Rate Limit Login */}
            <div>
              <label htmlFor="setting-rate-limit-login" className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Login Rate Limit (req/min)
              </label>
              <input
                id="setting-rate-limit-login"
                type="number"
                min="2"
                max="30"
                value={formRateLimitLogin}
                onChange={(e) => setFormRateLimitLogin(parseInt(e.target.value) || 5)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-1 block">Anti-bruteforce login throttle</span>
            </div>

            {/* SSE Keepalive Interval */}
            <div>
              <label htmlFor="setting-keepalive" className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                SSE Keepalive (seconds)
              </label>
              <input
                id="setting-keepalive"
                type="number"
                min="5"
                max="60"
                value={formKeepalive}
                onChange={(e) => setFormKeepalive(parseInt(e.target.value) || 15)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-1 block">Ping comment heartbeat interval</span>
            </div>

            {/* Max Upload Size */}
            <div>
              <label htmlFor="setting-max-upload" className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Max Document Upload (MB)
              </label>
              <input
                id="setting-max-upload"
                type="number"
                min="1"
                max="50"
                value={formMaxUploadMB}
                onChange={(e) => setFormMaxUploadMB(parseInt(e.target.value) || 20)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-1 block">1 MB to 50 MB hard cap</span>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-100 dark:border-slate-800">
            <button
              type="submit"
              disabled={savingSettings || formTopN > formTopK}
              className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs sm:text-sm font-semibold rounded-xl shadow-md transition flex items-center gap-2"
            >
              {savingSettings ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Saving Settings...
                </>
              ) : (
                'Save Runtime Settings'
              )}
            </button>
          </div>
        </form>
      </section>

      {/* Confirmation Modal for Reset */}
      {showResetConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-sm">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 max-w-md w-full p-6 shadow-2xl space-y-4">
            <h4 className="text-base font-bold text-slate-900 dark:text-white">
              Reset System Settings to Defaults?
            </h4>
            <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
              This action will reset retrieval parameters, thresholds, history windows, and rate limits to their baseline
              values from configuration (.env). A system audit log entry will be created.
            </p>
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowResetConfirm(false)}
                className="px-4 py-2 text-xs font-semibold text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleResetSettings}
                className="px-4 py-2 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 rounded-lg shadow"
              >
                Confirm Reset
              </button>
            </div>
          </div>
        </div>
      )}

      {/* SECTION 3 & 4: Architecture Specifications & Vector Store State */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Architecture Parameters (Immutable) */}
        <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
                <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
                Core Architecture Parameters
              </h3>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                Read-Only
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
              Determined by embedding weights and schema constraints. Changing requires database re-indexing.
            </p>

            {architecture && (
              <div className="space-y-3 text-xs">
                <div className="flex items-center justify-between py-2 border-b border-slate-100 dark:border-slate-800">
                  <span className="text-slate-500">Dense Embedding Model</span>
                  <span className="font-mono font-semibold text-slate-900 dark:text-white">{architecture.dense_model}</span>
                </div>
                <div className="flex items-center justify-between py-2 border-b border-slate-100 dark:border-slate-800">
                  <span className="text-slate-500">Vector Dimensionality</span>
                  <span className="font-mono font-semibold text-slate-900 dark:text-white">{architecture.dense_dim} dimensions</span>
                </div>
                <div className="flex items-center justify-between py-2 border-b border-slate-100 dark:border-slate-800">
                  <span className="text-slate-500">Sparse Model</span>
                  <span className="font-mono font-semibold text-slate-900 dark:text-white">{architecture.sparse_model}</span>
                </div>
                <div className="flex items-center justify-between py-2 border-b border-slate-100 dark:border-slate-800">
                  <span className="text-slate-500">Hybrid Fusion Algorithm</span>
                  <span className="font-semibold text-indigo-600 dark:text-indigo-400">{architecture.fusion_method} (k={architecture.rrf_k})</span>
                </div>
                <div className="flex items-center justify-between py-2 border-b border-slate-100 dark:border-slate-800">
                  <span className="text-slate-500">Reranker Model</span>
                  <span className="font-mono font-semibold text-slate-900 dark:text-white">{architecture.reranker_model}</span>
                </div>
                <div className="flex items-center justify-between py-2 border-b border-slate-100 dark:border-slate-800">
                  <span className="text-slate-500">Chunk Strategy</span>
                  <span className="font-mono font-semibold text-slate-900 dark:text-white">
                    {architecture.chunk_size} tokens (overlap: {architecture.chunk_overlap})
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Guardrail Layers list */}
          {architecture && (
            <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
              <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 block mb-2">
                Active Grounding Guardrail Layers:
              </span>
              <ul className="space-y-1.5">
                {architecture.guardrail_layers.map((layer, idx) => (
                  <li key={idx} className="text-[11px] text-slate-600 dark:text-slate-400 flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
                    {layer}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        {/* Vector Store & Collection State */}
        <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
                <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2 1.5 3 3.5 3h9c2 0 3.5-1 3.5-3V7c0-2-1.5-3-3.5-3h-9C5.5 4 4 5 4 7z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6" />
                </svg>
                Vector Store Synchronization
              </h3>
              {vectorStats && (
                <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">
                  {vectorStats.status}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
              Real-time vector points in Qdrant collection vs indexed documents in PostgreSQL.
            </p>

            {vectorStats && (
              <div className="grid grid-cols-2 gap-4">
                <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                  <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">Indexed Documents</span>
                  <div className="text-xl font-bold text-slate-900 dark:text-white mt-0.5">
                    {vectorStats.indexed_documents_count}
                  </div>
                  <span className="text-[10px] text-slate-400 block mt-1">PostgreSQL active rows</span>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                  <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">Vector Points</span>
                  <div className="text-xl font-bold text-slate-900 dark:text-white mt-0.5">
                    {vectorStats.points_count}
                  </div>
                  <span className="text-[10px] text-slate-400 block mt-1">Qdrant chunk vectors</span>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                  <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">Collection Name</span>
                  <div className="text-sm font-mono font-bold text-slate-900 dark:text-white mt-1 truncate">
                    {vectorStats.collection_name}
                  </div>
                  <span className="text-[10px] text-slate-400 block mt-1">{vectorStats.segments_count} segments</span>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                  <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">Active Document Versions</span>
                  <div className="text-xl font-bold text-slate-900 dark:text-white mt-0.5">
                    {vectorStats.active_versions_count}
                  </div>
                  <span className="text-[10px] text-slate-400 block mt-1">{vectorStats.superseded_versions_count} superseded</span>
                </div>
              </div>
            )}
          </div>

          <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500">
            <span>Dual Named Vectors: dense (1024d) + BM25 sparse</span>
            <span className="text-emerald-600 dark:text-emerald-400 font-medium">✓ In Sync</span>
          </div>
        </section>
      </div>

      {/* SECTION 5 & 6: Background Workers & Chat Quality Telemetry */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Celery Workers & Reconciler */}
        <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm">
          <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-4 flex items-center gap-2">
            <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z" />
            </svg>
            Background Workers & Document Reconciler
          </h3>

          {workers && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800 text-center">
                  <span className="text-[10px] font-semibold uppercase text-slate-400">Online Workers</span>
                  <div className="text-lg font-bold text-slate-900 dark:text-white mt-0.5">
                    {workers.online_workers_count}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800 text-center">
                  <span className="text-[10px] font-semibold uppercase text-slate-400">Active Tasks</span>
                  <div className="text-lg font-bold text-slate-900 dark:text-white mt-0.5">
                    {workers.active_tasks_count}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800 text-center">
                  <span className="text-[10px] font-semibold uppercase text-slate-400">Queue Length</span>
                  <div className="text-lg font-bold text-slate-900 dark:text-white mt-0.5">
                    {workers.queue_length}
                  </div>
                </div>
              </div>

              {/* Reconciler Task details */}
              <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-slate-800 dark:text-slate-200">
                    Document Stale Reconciler Task
                  </span>
                  <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-semibold">
                    {workers.reconciler_last_status || 'Scheduled (Every 15m)'}
                  </span>
                </div>
                <div className="text-xs text-slate-500 space-y-1">
                  <div className="flex justify-between">
                    <span>Last Execution:</span>
                    <span className="font-mono text-slate-700 dark:text-slate-300">
                      {workers.last_reconciler_run
                        ? new Date(workers.last_reconciler_run).toLocaleString()
                        : 'Running periodically'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Stale Ingestions Fixed:</span>
                    <span className="font-mono font-bold text-slate-700 dark:text-slate-300">
                      {workers.reconciler_fixed_count}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>

        {/* Chat Quality & Grounding Indicators */}
        <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
              <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
              Chat Quality & Guardrail Telemetry
            </h3>

            {/* Window toggle */}
            <div className="flex rounded-lg border border-slate-200 dark:border-slate-800 p-0.5 bg-slate-50 dark:bg-slate-800">
              <button
                onClick={() => setQualityWindow('24h')}
                className={`px-2.5 py-1 text-xs font-semibold rounded-md transition ${
                  qualityWindow === '24h'
                    ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-300 shadow-sm'
                    : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
              >
                24 Hours
              </button>
              <button
                onClick={() => setQualityWindow('7d')}
                className={`px-2.5 py-1 text-xs font-semibold rounded-md transition ${
                  qualityWindow === '7d'
                    ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-300 shadow-sm'
                    : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
              >
                7 Days
              </button>
            </div>
          </div>

          {quality && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                  <span className="text-[11px] font-medium text-slate-500">Total User Queries</span>
                  <div className="text-xl font-bold text-slate-900 dark:text-white mt-0.5">
                    {quality.total_queries}
                  </div>
                  <span className="text-[10px] text-slate-400 block mt-1">Telemetry events logged</span>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                  <span className="text-[11px] font-medium text-slate-500">Fallback Rate</span>
                  <div className="text-xl font-bold text-slate-900 dark:text-white mt-0.5">
                    {(quality.fallback_rate * 100).toFixed(1)}%
                  </div>
                  <span className="text-[10px] text-slate-400 block mt-1">{quality.fallback_count} total fallbacks</span>
                </div>
              </div>

              {/* Guardrail Breakdown */}
              <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 text-xs space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-slate-600 dark:text-slate-400">Layer 1: Low-Score Fallback</span>
                  <span className="font-mono font-bold text-slate-800 dark:text-slate-200">
                    {quality.layer1_fallback_count}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-600 dark:text-slate-400">Layer 2: Sentinel Intercept</span>
                  <span className="font-mono font-bold text-slate-800 dark:text-slate-200">
                    {quality.layer2_fallback_count}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-600 dark:text-slate-400">Layer 3: Ungrounded Retract</span>
                  <span className="font-mono font-bold text-slate-800 dark:text-slate-200">
                    {quality.layer3_fallback_count}
                  </span>
                </div>
                <div className="flex justify-between items-center pt-2 border-t border-slate-200 dark:border-slate-700">
                  <span className="text-slate-600 dark:text-slate-400">Avg Retrieval Score</span>
                  <span className="font-mono font-bold text-indigo-600 dark:text-indigo-400">
                    {quality.avg_retrieval_score ? quality.avg_retrieval_score.toFixed(3) : 'N/A'}
                  </span>
                </div>
              </div>

              <p className="text-[11px] text-slate-400 italic">
                Strict Privacy: Zero user messages or generated answers are logged or exposed in telemetry.
              </p>
            </div>
          )}
        </section>
      </div>

      {/* SECTION 7: Dynamic API Routes Introspection */}
      <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
              <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
              Registered API Routes ({routesData?.routes.length || 0})
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Live FastAPI OpenAPI endpoints and access levels.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Search route or path..."
              value={routeSearch}
              onChange={(e) => setRouteSearch(e.target.value)}
              className="px-3 py-1.5 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500"
            />
            {routesData && (
              <a
                href={routesData.docs_url}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-1.5 text-xs font-semibold text-indigo-600 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800 rounded-lg hover:bg-indigo-50 dark:hover:bg-indigo-950/40"
              >
                Swagger UI ↗
              </a>
            )}
          </div>
        </div>

        <div className="overflow-x-auto max-h-96 border border-slate-200 dark:border-slate-800 rounded-xl">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 dark:bg-slate-800/80 sticky top-0 border-b border-slate-200 dark:border-slate-700 text-slate-500">
              <tr>
                <th className="px-4 py-2.5 font-semibold">Method</th>
                <th className="px-4 py-2.5 font-semibold">Path</th>
                <th className="px-4 py-2.5 font-semibold">Summary</th>
                <th className="px-4 py-2.5 font-semibold">Auth Level</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {filteredRoutes.map((r, i) => {
                const methodColor =
                  r.method === 'GET'
                    ? 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300'
                    : r.method === 'POST'
                    ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                    : r.method === 'PUT'
                    ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
                    : r.method === 'DELETE'
                    ? 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300'
                    : 'bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300';

                return (
                  <tr key={i} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
                    <td className="px-4 py-2">
                      <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold ${methodColor}`}>
                        {r.method}
                      </span>
                    </td>
                    <td className="px-4 py-2 font-mono text-slate-900 dark:text-slate-100 font-medium">
                      {r.path}
                    </td>
                    <td className="px-4 py-2 text-slate-500 dark:text-slate-400 truncate max-w-xs">
                      {r.summary || '—'}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                          r.auth_level === 'admin'
                            ? 'bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300'
                            : r.auth_level === 'user'
                            ? 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300'
                            : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-400'
                        }`}
                      >
                        {r.auth_level}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* SECTION 8: Recent Activity & Audit Trail */}
      <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm">
        <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-4 flex items-center gap-2">
          <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Recent Admin Audit Trail & Errors
        </h3>

        <div className="overflow-x-auto max-h-72 border border-slate-200 dark:border-slate-800 rounded-xl">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 dark:bg-slate-800/80 sticky top-0 border-b border-slate-200 dark:border-slate-700 text-slate-500">
              <tr>
                <th className="px-4 py-2 font-semibold">Timestamp</th>
                <th className="px-4 py-2 font-semibold">Action</th>
                <th className="px-4 py-2 font-semibold">Admin User</th>
                <th className="px-4 py-2 font-semibold">Target</th>
                <th className="px-4 py-2 font-semibold">Details / Warning</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {activity && activity.audit_logs.length > 0 ? (
                activity.audit_logs.map((log) => (
                  <tr key={log.id} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
                    <td className="px-4 py-2 text-slate-400 whitespace-nowrap">
                      {new Date(log.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2 font-semibold text-slate-800 dark:text-slate-200">
                      {log.action}
                    </td>
                    <td className="px-4 py-2 text-slate-600 dark:text-slate-400">
                      {log.user_email || 'System'}
                    </td>
                    <td className="px-4 py-2 font-mono text-[11px] text-slate-500">
                      {log.target_type || '—'}
                    </td>
                    <td className="px-4 py-2 text-[11px]">
                      {log.details?.warning ? (
                        <span className="text-amber-600 dark:text-amber-400 font-medium">
                          ⚠️ {log.details.warning}
                        </span>
                      ) : (
                        <span className="text-slate-400">
                          {log.details ? `v${log.details.version || 'OK'}` : '—'}
                        </span>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                    No recent audit events recorded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* SECTION 9: Allowlisted Environment Inspection */}
      <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
              <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
              Environment & Infrastructure Inspection
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Safe allowlist of operational environment parameters.
            </p>
          </div>
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300">
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
            Secret Protection Verified
          </span>
        </div>

        <div className="overflow-x-auto border border-slate-200 dark:border-slate-800 rounded-xl">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 dark:bg-slate-800/80 border-b border-slate-200 dark:border-slate-700 text-slate-500">
              <tr>
                <th className="px-4 py-2.5 font-semibold">Variable</th>
                <th className="px-4 py-2.5 font-semibold">Value</th>
                <th className="px-4 py-2.5 font-semibold">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800 font-mono">
              {environment?.settings.map((item) => (
                <tr key={item.key} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
                  <td className="px-4 py-2 font-bold text-slate-800 dark:text-slate-200">
                    {item.key}
                  </td>
                  <td className="px-4 py-2 text-indigo-600 dark:text-indigo-400 font-medium truncate max-w-md">
                    {item.value}
                  </td>
                  <td className="px-4 py-2 font-sans text-slate-500 dark:text-slate-400">
                    {item.description || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
