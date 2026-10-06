'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { DocumentItem, DocumentStatus } from '@/types/chat';
import {
  fetchDocuments,
  uploadDocumentFile,
  uploadDocumentUrl,
  updateDocumentFile,
  deleteDocument,
} from '@/services/api';
import {
  Upload,
  Globe,
  FileText,
  RefreshCw,
  Trash2,
  AlertCircle,
  CheckCircle2,
  Clock,
  Layers,
  ArrowUpCircle,
  File,
  X,
  AlertTriangle,
  Loader2,
  ExternalLink,
  Plus,
} from 'lucide-react';

export default function AdminDocManager() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState<'file' | 'url'>('file');

  // File upload state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  // URL upload state
  const [urlInput, setUrlInput] = useState('');
  const [urlNameInput, setUrlNameInput] = useState('');
  const [isIngestingUrl, setIsIngestingUrl] = useState(false);

  // Alerts
  const [successBanner, setSuccessBanner] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Modals state
  const [docToDelete, setDocToDelete] = useState<DocumentItem | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const [docToUpdate, setDocToUpdate] = useState<DocumentItem | null>(null);
  const [newVersionFile, setNewVersionFile] = useState<File | null>(null);
  const [isUpdatingVersion, setIsUpdatingVersion] = useState(false);

  const [errorDetailsDoc, setErrorDetailsDoc] = useState<DocumentItem | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const updateFileInputRef = useRef<HTMLInputElement>(null);

  // Load documents
  const loadDocs = useCallback(async (isManual = false) => {
    if (isManual) setIsRefreshing(true);
    try {
      const data = await fetchDocuments();
      setDocuments(data);
      setErrorBanner(null);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to load documents');
    } finally {
      setIsLoading(false);
      if (isManual) setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  // Polling mechanism while any document is in-flight
  useEffect(() => {
    const hasInFlight = documents.some((d) =>
      ['pending', 'processing', 'updating', 'deleting'].includes(d.status)
    );

    if (!hasInFlight) return;

    const intervalId = setInterval(() => {
      loadDocs();
    }, 2500);

    return () => clearInterval(intervalId);
  }, [documents, loadDocs]);

  // Handle file upload
  const handleFileUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) return;

    setIsUploading(true);
    setErrorBanner(null);
    setSuccessBanner(null);

    try {
      const res = await uploadDocumentFile(selectedFile);
      setSuccessBanner(`Upload accepted for "${selectedFile.name}". Ingestion started.`);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await loadDocs();
    } catch (err: any) {
      setErrorBanner(err.message || 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  };

  // Handle URL ingestion
  const handleUrlIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!urlInput.trim()) return;

    setIsIngestingUrl(true);
    setErrorBanner(null);
    setSuccessBanner(null);

    try {
      const res = await uploadDocumentUrl(urlInput.trim(), urlNameInput.trim() || undefined);
      setSuccessBanner(`URL ingestion accepted for "${urlNameInput || urlInput}". Ingestion started.`);
      setUrlInput('');
      setUrlNameInput('');
      await loadDocs();
    } catch (err: any) {
      setErrorBanner(err.message || 'URL ingestion failed');
    } finally {
      setIsIngestingUrl(false);
    }
  };

  // Handle Delete Confirmation
  const confirmDelete = async () => {
    if (!docToDelete) return;
    setIsDeleting(true);
    setErrorBanner(null);

    try {
      await deleteDocument(docToDelete.id);
      setSuccessBanner(`Deletion initiated for "${docToDelete.name}". It is immediately hidden from searches.`);
      setDocToDelete(null);
      await loadDocs();
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to delete document');
    } finally {
      setIsDeleting(false);
    }
  };

  // Handle Version Update
  const confirmUpdateVersion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!docToUpdate || !newVersionFile) return;

    setIsUpdatingVersion(true);
    setErrorBanner(null);

    try {
      await updateDocumentFile(docToUpdate.id, newVersionFile);
      setSuccessBanner(`Update accepted for "${docToUpdate.name}". Blue-green cutover initiated.`);
      setDocToUpdate(null);
      setNewVersionFile(null);
      if (updateFileInputRef.current) updateFileInputRef.current.value = '';
      await loadDocs();
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to update document version');
    } finally {
      setIsUpdatingVersion(false);
    }
  };

  const formatBytes = (bytes?: number) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return 'N/A';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return dateStr;
    }
  };

  const renderStatusBadge = (status: DocumentStatus | string, lastError?: string | null, doc?: DocumentItem) => {
    switch (status) {
      case 'active':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Active
          </span>
        );
      case 'processing':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20 animate-pulse">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Processing
          </span>
        );
      case 'updating':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 animate-pulse">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            Updating
          </span>
        );
      case 'pending':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <Clock className="w-3.5 h-3.5" />
            Pending
          </span>
        );
      case 'deleting':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <Trash2 className="w-3.5 h-3.5 animate-pulse" />
            Deleting
          </span>
        );
      case 'failed':
        return (
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-red-500/10 text-red-400 border border-red-500/20">
              <AlertCircle className="w-3.5 h-3.5" />
              Failed
            </span>
            {doc && (
              <button
                type="button"
                onClick={() => setErrorDetailsDoc(doc)}
                className="text-[11px] text-red-400 hover:text-red-300 underline font-medium"
              >
                View Error
              </button>
            )}
          </div>
        );
      default:
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs text-gray-400 bg-gray-800">
            {status}
          </span>
        );
    }
  };

  const renderTypeIcon = (type: string) => {
    switch (type.toLowerCase()) {
      case 'pdf':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-500/15 text-red-400 border border-red-500/20">PDF</span>;
      case 'docx':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-500/15 text-blue-400 border border-blue-500/20">DOCX</span>;
      case 'md':
      case 'markdown':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-purple-500/15 text-purple-400 border border-purple-500/20">MD</span>;
      case 'url':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">URL</span>;
      default:
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-gray-500/15 text-gray-400 border border-gray-500/20">TXT</span>;
    }
  };

  const activeCount = documents.filter((d) => d.status === 'active').length;
  const inProgressCount = documents.filter((d) => ['pending', 'processing', 'updating', 'deleting'].includes(d.status)).length;
  const failedCount = documents.filter((d) => d.status === 'failed').length;

  return (
    <div className="space-y-6 animate-fade-in max-w-7xl mx-auto pb-12">
      {/* Top Banner Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <div className="glass-panel p-4 rounded-2xl flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gray-800/80 text-gray-300 flex items-center justify-center border border-gray-700">
            <FileText className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-gray-400 font-medium">Total Documents</div>
            <div className="text-xl font-bold text-white">{documents.length}</div>
          </div>
        </div>

        <div className="glass-panel p-4 rounded-2xl flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center border border-emerald-500/20">
            <CheckCircle2 className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-emerald-400/80 font-medium">Active (Grounded)</div>
            <div className="text-xl font-bold text-emerald-300">{activeCount}</div>
          </div>
        </div>

        <div className="glass-panel p-4 rounded-2xl flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center border border-blue-500/20">
            <Loader2 className={`w-5 h-5 ${inProgressCount > 0 ? 'animate-spin' : ''}`} />
          </div>
          <div>
            <div className="text-xs text-blue-400/80 font-medium">In Progress</div>
            <div className="text-xl font-bold text-blue-300">{inProgressCount}</div>
          </div>
        </div>

        <div className="glass-panel p-4 rounded-2xl flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-red-500/10 text-red-400 flex items-center justify-center border border-red-500/20">
            <AlertCircle className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-red-400/80 font-medium">Failed</div>
            <div className="text-xl font-bold text-red-300">{failedCount}</div>
          </div>
        </div>
      </div>

      {/* Action feedback banners */}
      {successBanner && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm flex items-center justify-between animate-fade-in">
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            <span>{successBanner}</span>
          </div>
          <button onClick={() => setSuccessBanner(null)} className="text-emerald-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {errorBanner && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-sm flex items-center justify-between animate-fade-in">
          <div className="flex items-center gap-2.5">
            <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
            <span>{errorBanner}</span>
          </div>
          <button onClick={() => setErrorBanner(null)} className="text-red-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Ingestion Section Card */}
      <div className="glass-panel p-6 rounded-2xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6 pb-4 border-b border-gray-800">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Upload className="w-5 h-5 text-emerald-400" />
              <span>Ingest Knowledge Base Sources</span>
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Upload local documents or submit trusted web URLs to embed into Qdrant.
            </p>
          </div>

          {/* Mode Switcher */}
          <div className="flex rounded-xl bg-gray-900/80 p-1 border border-gray-800 self-start sm:self-auto">
            <button
              type="button"
              onClick={() => setActiveTab('file')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'file'
                  ? 'bg-emerald-600 text-white shadow-md'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <File className="w-3.5 h-3.5" />
              <span>File Upload</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('url')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'url'
                  ? 'bg-emerald-600 text-white shadow-md'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <Globe className="w-3.5 h-3.5" />
              <span>Web URL</span>
            </button>
          </div>
        </div>

        {/* Tab 1: File Upload Form */}
        {activeTab === 'file' && (
          <form onSubmit={handleFileUpload} className="space-y-4">
            <div className="border-2 border-dashed border-gray-800 hover:border-emerald-500/40 rounded-2xl p-6 text-center transition-colors bg-gray-950/40">
              <input
                ref={fileInputRef}
                id="file-upload-input"
                type="file"
                accept=".pdf,.docx,.md,.txt"
                onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                className="hidden"
              />
              <label htmlFor="file-upload-input" className="cursor-pointer block">
                <div className="w-12 h-12 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center mx-auto mb-3 border border-emerald-500/20">
                  <Upload className="w-6 h-6" />
                </div>
                {selectedFile ? (
                  <div>
                    <span className="font-semibold text-white text-sm">{selectedFile.name}</span>
                    <span className="text-xs text-gray-400 block mt-1">({formatBytes(selectedFile.size)})</span>
                  </div>
                ) : (
                  <div>
                    <span className="text-sm font-semibold text-white block">Click to select a file, or drag and drop</span>
                    <span className="text-xs text-gray-400 mt-1 block">Supports PDF, DOCX, Markdown (.md), and TXT (Max 20MB)</span>
                  </div>
                )}
              </label>
            </div>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={!selectedFile || isUploading}
                className="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-emerald-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {isUploading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Uploading & Parsing...</span>
                  </>
                ) : (
                  <>
                    <Plus className="w-4 h-4" />
                    <span>Upload Document</span>
                  </>
                )}
              </button>
            </div>
          </form>
        )}

        {/* Tab 2: Web URL Ingestion Form */}
        {activeTab === 'url' && (
          <form onSubmit={handleUrlIngest} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="sm:col-span-2">
                <label className="block text-xs font-semibold text-gray-300 uppercase tracking-wider mb-2">
                  Target Web URL
                </label>
                <div className="relative">
                  <Globe className="w-4 h-4 text-gray-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="url"
                    value={urlInput}
                    onChange={(e) => setUrlInput(e.target.value)}
                    placeholder="https://example.com/documentation"
                    required
                    className="glass-input w-full pl-10 pr-4 py-2.5 rounded-xl text-xs text-white placeholder-gray-500 focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-300 uppercase tracking-wider mb-2">
                  Document Name (Optional)
                </label>
                <input
                  type="text"
                  value={urlNameInput}
                  onChange={(e) => setUrlNameInput(e.target.value)}
                  placeholder="e.g. Official Documentation"
                  className="glass-input w-full px-4 py-2.5 rounded-xl text-xs text-white placeholder-gray-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={!urlInput.trim() || isIngestingUrl}
                className="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-emerald-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {isIngestingUrl ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Fetching & Scraping...</span>
                  </>
                ) : (
                  <>
                    <Plus className="w-4 h-4" />
                    <span>Ingest Web Page</span>
                  </>
                )}
              </button>
            </div>
          </form>
        )}
      </div>

      {/* Documents Table Section */}
      <div className="glass-panel p-6 rounded-2xl">
        <div className="flex items-center justify-between mb-6 pb-4 border-b border-gray-800">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Layers className="w-5 h-5 text-emerald-400" />
              <span>Indexed Documents</span>
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              All documents indexed in PostgreSQL and vector storage. Polling activates automatically when tasks are in progress.
            </p>
          </div>

          <button
            type="button"
            onClick={() => loadDocs(true)}
            disabled={isRefreshing}
            className="px-3.5 py-2 rounded-xl bg-gray-900 hover:bg-gray-800 text-gray-300 hover:text-white border border-gray-800 text-xs font-semibold flex items-center gap-2 transition-all disabled:opacity-50"
            title="Refresh documents list"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-emerald-400' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>

        {/* Table wrapper */}
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="py-16 text-center text-gray-400 text-xs flex flex-col items-center justify-center gap-3">
              <Loader2 className="w-7 h-7 animate-spin text-emerald-400" />
              <span>Loading documents table...</span>
            </div>
          ) : documents.length === 0 ? (
            <div className="py-16 text-center text-gray-500 text-xs">
              No documents currently in knowledge base. Upload a document above to get started.
            </div>
          ) : (
            <table className="w-full text-left text-xs text-gray-300 border-collapse">
              <thead>
                <tr className="border-b border-gray-800/80 text-[11px] uppercase tracking-wider text-gray-400 bg-gray-950/40">
                  <th className="py-3 px-4 font-semibold">Format</th>
                  <th className="py-3 px-4 font-semibold">Document Name</th>
                  <th className="py-3 px-4 font-semibold">Status</th>
                  <th className="py-3 px-4 font-semibold">Version</th>
                  <th className="py-3 px-4 font-semibold">Size</th>
                  <th className="py-3 px-4 font-semibold">Uploaded</th>
                  <th className="py-3 px-4 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {documents.map((doc) => {
                  const isPendingVersion = doc.pending_version && doc.pending_version !== doc.active_version;
                  return (
                    <tr key={doc.id} className="hover:bg-gray-900/40 transition-colors">
                      <td className="py-3.5 px-4 whitespace-nowrap">
                        {renderTypeIcon(doc.source_type)}
                      </td>

                      <td className="py-3.5 px-4 font-medium text-white max-w-xs truncate" title={doc.name}>
                        {doc.name}
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap">
                        {renderStatusBadge(doc.status, doc.last_error, doc)}
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap">
                        <span className="font-mono text-gray-300">
                          v{doc.active_version ?? 1}
                          {isPendingVersion && (
                            <span className="text-[10px] text-indigo-400 ml-1.5 font-sans">
                              (updating v{doc.pending_version})
                            </span>
                          )}
                        </span>
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap text-gray-400">
                        {formatBytes(doc.size_bytes)}
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap text-gray-400">
                        {formatDate(doc.created_at)}
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap text-right">
                        <div className="flex items-center justify-end gap-2">
                          {/* New version button */}
                          <button
                            type="button"
                            onClick={() => {
                              setDocToUpdate(doc);
                              setNewVersionFile(null);
                            }}
                            className="p-1.5 rounded-lg text-gray-400 hover:text-emerald-300 hover:bg-emerald-500/10 transition-colors"
                            title="Upload New Version"
                          >
                            <ArrowUpCircle className="w-4 h-4" />
                          </button>

                          {/* Delete button */}
                          <button
                            type="button"
                            onClick={() => setDocToDelete(doc)}
                            className="p-1.5 rounded-lg text-gray-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                            title="Delete Document"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Modal: Delete Confirmation */}
      {docToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-md glass-panel-elevated p-6 rounded-2xl shadow-2xl border border-gray-800 animate-slide-up">
            <div className="flex items-center gap-3 text-red-400 mb-4">
              <div className="w-10 h-10 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-5 h-5 text-red-400" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">Delete Document</h3>
                <p className="text-xs text-gray-400">Two-phase deletion confirmation</p>
              </div>
            </div>

            <p className="text-xs text-gray-300 leading-relaxed mb-4">
              Are you sure you want to delete <strong className="text-white">"{docToDelete.name}"</strong>?
            </p>
            <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-[11px] text-red-300 mb-6 leading-relaxed">
              <strong>Phase 1:</strong> Immediately hides this document from search results.
              <br />
              <strong>Phase 2:</strong> Asynchronously purges chunk vectors and files from storage.
            </div>

            <div className="flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setDocToDelete(null)}
                disabled={isDeleting}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                disabled={isDeleting}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-red-600 hover:bg-red-500 text-white flex items-center gap-2 shadow-lg shadow-red-600/20 transition-all disabled:opacity-50"
              >
                {isDeleting ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Deleting...</span>
                  </>
                ) : (
                  <span>Delete Document</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: New Version Upload */}
      {docToUpdate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-md glass-panel-elevated p-6 rounded-2xl shadow-2xl border border-gray-800 animate-slide-up">
            <div className="flex items-center justify-between mb-4 pb-2 border-b border-gray-800">
              <div className="flex items-center gap-2.5">
                <ArrowUpCircle className="w-5 h-5 text-emerald-400" />
                <h3 className="text-base font-bold text-white">Upload New Version</h3>
              </div>
              <button
                onClick={() => setDocToUpdate(null)}
                className="text-gray-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={confirmUpdateVersion} className="space-y-4">
              <p className="text-xs text-gray-300">
                Updating <strong className="text-white">"{docToUpdate.name}"</strong> (current version: v{docToUpdate.active_version || 1}).
              </p>
              <p className="text-[11px] text-gray-400">
                The current version remains searchable until the new version is embedded, ensuring zero search downtime (Blue-Green cutover).
              </p>

              <div className="border border-dashed border-gray-700 rounded-xl p-4 text-center">
                <input
                  ref={updateFileInputRef}
                  id="new-version-file-input"
                  type="file"
                  accept=".pdf,.docx,.md,.txt"
                  onChange={(e) => setNewVersionFile(e.target.files?.[0] || null)}
                  className="hidden"
                />
                <label htmlFor="new-version-file-input" className="cursor-pointer block">
                  <Upload className="w-6 h-6 text-gray-400 mx-auto mb-2" />
                  {newVersionFile ? (
                    <span className="text-xs font-semibold text-emerald-400">{newVersionFile.name}</span>
                  ) : (
                    <span className="text-xs text-gray-400">Click to choose revised file</span>
                  )}
                </label>
              </div>

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setDocToUpdate(null)}
                  disabled={isUpdatingVersion}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-gray-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!newVersionFile || isUpdatingVersion}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-2 shadow-lg shadow-emerald-500/20 disabled:opacity-40"
                >
                  {isUpdatingVersion ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Uploading...</span>
                    </>
                  ) : (
                    <span>Update Version</span>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Error Details */}
      {errorDetailsDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-lg glass-panel-elevated p-6 rounded-2xl shadow-2xl border border-gray-800 animate-slide-up">
            <div className="flex items-center justify-between mb-4 pb-2 border-b border-gray-800">
              <div className="flex items-center gap-2 text-red-400">
                <AlertCircle className="w-5 h-5" />
                <h3 className="text-base font-bold text-white">Ingestion Error Diagnostics</h3>
              </div>
              <button
                onClick={() => setErrorDetailsDoc(null)}
                className="text-gray-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div className="text-xs text-gray-300">
                <span className="text-gray-500">Document: </span>
                <strong className="text-white">{errorDetailsDoc.name}</strong>
              </div>
              <div className="text-xs text-gray-300">
                <span className="text-gray-500">Document ID: </span>
                <span className="font-mono text-gray-400">{errorDetailsDoc.id}</span>
              </div>
              <div>
                <span className="text-xs text-gray-500 block mb-1">Last Error Message:</span>
                <pre className="p-3 rounded-xl bg-gray-950 border border-gray-800 text-red-300 text-xs font-mono whitespace-pre-wrap max-h-56 overflow-y-auto leading-relaxed">
                  {errorDetailsDoc.last_error || 'No additional error detail available.'}
                </pre>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={() => setErrorDetailsDoc(null)}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-gray-800 hover:bg-gray-700 text-white"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
