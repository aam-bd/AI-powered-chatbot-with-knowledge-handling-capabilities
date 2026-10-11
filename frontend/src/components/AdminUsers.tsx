'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { User, UserRole } from '@/types/chat';
import { useAuth } from '@/context/AuthContext';
import { fetchUsers, updateUser } from '@/services/api';
import {
  Users,
  Shield,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  UserX,
  RefreshCw,
  AlertTriangle,
  Loader2,
  CheckCircle2,
  X,
  Mail,
  Calendar,
} from 'lucide-react';

export default function AdminUsers() {
  const { user: currentAdmin } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Notifications
  const [successBanner, setSuccessBanner] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Role change modal
  const [roleModalUser, setRoleModalUser] = useState<User | null>(null);
  const [targetRole, setTargetRole] = useState<UserRole>('user');
  const [isUpdatingRole, setIsUpdatingRole] = useState(false);

  // Status change modal (activate / deactivate)
  const [statusModalUser, setStatusModalUser] = useState<User | null>(null);
  const [targetStatus, setTargetStatus] = useState<boolean>(true);
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);

  const loadUsers = useCallback(async (quiet = false) => {
    if (!quiet) setIsLoading(true);
    else setIsRefreshing(true);

    try {
      const data = await fetchUsers(0, 100);
      setUsers(data);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to load users');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const handleOpenRoleModal = (u: User) => {
    setErrorBanner(null);
    setSuccessBanner(null);
    const newRole: UserRole = u.role === 'admin' ? 'user' : 'admin';
    setRoleModalUser(u);
    setTargetRole(newRole);
  };

  const handleConfirmRoleChange = async () => {
    if (!roleModalUser) return;
    setIsUpdatingRole(true);
    setErrorBanner(null);

    try {
      const updated = await updateUser(roleModalUser.id, { role: targetRole });
      setSuccessBanner(`Successfully updated ${roleModalUser.email}'s role to ${targetRole}.`);
      setRoleModalUser(null);
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)));
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to change user role');
    } finally {
      setIsUpdatingRole(false);
    }
  };

  const handleOpenStatusModal = (u: User) => {
    setErrorBanner(null);
    setSuccessBanner(null);
    const newStatus = !u.is_active;
    setStatusModalUser(u);
    setTargetStatus(newStatus);
  };

  const handleConfirmStatusChange = async () => {
    if (!statusModalUser) return;
    setIsUpdatingStatus(true);
    setErrorBanner(null);

    try {
      const updated = await updateUser(statusModalUser.id, { is_active: targetStatus });
      setSuccessBanner(
        `Successfully ${targetStatus ? 'activated' : 'deactivated'} ${statusModalUser.email}.`
      );
      setStatusModalUser(null);
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)));
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to update user status');
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Banner Notifications */}
      {errorBanner && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center justify-between animate-fade-in shadow-lg">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span className="font-medium">{errorBanner}</span>
          </div>
          <button
            onClick={() => setErrorBanner(null)}
            className="p-1 hover:bg-red-500/20 rounded-md transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {successBanner && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs flex items-center justify-between animate-fade-in shadow-lg">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span className="font-medium">{successBanner}</span>
          </div>
          <button
            onClick={() => setSuccessBanner(null)}
            className="p-1 hover:bg-emerald-500/20 rounded-md transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Header & Controls */}
      <div className="glass-panel p-6 rounded-2xl border border-gray-800 shadow-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-white flex items-center gap-2">
            <Users className="w-5 h-5 text-emerald-400" />
            <span>Registered User Accounts</span>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              {users.length} {users.length === 1 ? 'user' : 'users'}
            </span>
          </h2>
          <p className="text-xs text-gray-400 mt-1">
            Manage user roles, grant administrator privileges, and toggle account activation.
          </p>
        </div>

        <button
          onClick={() => loadUsers(true)}
          disabled={isLoading || isRefreshing}
          className="px-3 py-2 rounded-xl bg-gray-900/80 hover:bg-gray-800 text-gray-300 hover:text-white border border-gray-800 text-xs font-semibold flex items-center gap-2 transition-all shrink-0 self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Users Table */}
      <div className="glass-panel rounded-2xl border border-gray-800 shadow-2xl overflow-hidden">
        {isLoading ? (
          <div className="p-12 flex flex-col items-center justify-center text-gray-400 gap-3">
            <Loader2 className="w-8 h-8 animate-spin text-emerald-400" />
            <p className="text-xs">Loading user registry...</p>
          </div>
        ) : users.length === 0 ? (
          <div className="p-12 text-center text-gray-500 text-xs">No registered users found.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-900/50 text-gray-400 font-semibold uppercase tracking-wider text-[10px]">
                  <th className="py-3.5 px-6">User / Email</th>
                  <th className="py-3.5 px-4">Role</th>
                  <th className="py-3.5 px-4">Status</th>
                  <th className="py-3.5 px-4">Registered</th>
                  <th className="py-3.5 px-6 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {users.map((u) => {
                  const isSelf = currentAdmin?.id === u.id;

                  return (
                    <tr
                      key={u.id}
                      className="hover:bg-gray-800/30 transition-colors group text-gray-300"
                    >
                      {/* Email / ID */}
                      <td className="py-4 px-6">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-xl bg-gray-800/80 border border-gray-700/60 flex items-center justify-center text-gray-300 shrink-0">
                            <Mail className="w-3.5 h-3.5" />
                          </div>
                          <div>
                            <div className="font-semibold text-white flex items-center gap-2">
                              <span>{u.email}</span>
                              {isSelf && (
                                <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 uppercase">
                                  You
                                </span>
                              )}
                            </div>
                            <span className="text-[10px] text-gray-500 font-mono block">
                              ID: {u.id}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Role */}
                      <td className="py-4 px-4">
                        {u.role === 'admin' ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-semibold bg-purple-500/10 text-purple-300 border border-purple-500/20">
                            <Shield className="w-3 h-3 text-purple-400" />
                            Admin
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-semibold bg-blue-500/10 text-blue-300 border border-blue-500/20">
                            <UserCheck className="w-3 h-3 text-blue-400" />
                            User
                          </span>
                        )}
                      </td>

                      {/* Active Status */}
                      <td className="py-4 px-4">
                        {u.is_active ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-semibold bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                            Active
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-semibold bg-red-500/10 text-red-300 border border-red-500/20">
                            <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                            Inactive
                          </span>
                        )}
                      </td>

                      {/* Created At */}
                      <td className="py-4 px-4 text-gray-400 text-[11px]">
                        <div className="flex items-center gap-1.5">
                          <Calendar className="w-3 h-3 text-gray-500 shrink-0" />
                          <span>
                            {u.created_at
                              ? new Date(u.created_at).toLocaleDateString(undefined, {
                                  month: 'short',
                                  day: 'numeric',
                                  year: 'numeric',
                                })
                              : '—'}
                          </span>
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="py-4 px-6 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {/* Role toggle button */}
                          <button
                            onClick={() => handleOpenRoleModal(u)}
                            disabled={isSelf}
                            title={
                              isSelf
                                ? 'You cannot change your own role'
                                : u.role === 'admin'
                                ? 'Demote to standard user'
                                : 'Promote to administrator'
                            }
                            className={`px-2.5 py-1.5 rounded-lg text-[11px] font-medium border transition-colors flex items-center gap-1.5 ${
                              isSelf
                                ? 'opacity-40 cursor-not-allowed bg-gray-900 border-gray-800 text-gray-500'
                                : u.role === 'admin'
                                ? 'bg-purple-950/20 hover:bg-purple-900/40 text-purple-300 border-purple-800/40'
                                : 'bg-gray-800/70 hover:bg-gray-700 text-gray-200 border-gray-700'
                            }`}
                          >
                            <Shield className="w-3 h-3" />
                            <span>{u.role === 'admin' ? 'Demote' : 'Make Admin'}</span>
                          </button>

                          {/* Status toggle button */}
                          <button
                            onClick={() => handleOpenStatusModal(u)}
                            disabled={isSelf}
                            title={
                              isSelf
                                ? 'You cannot deactivate your own account'
                                : u.is_active
                                ? 'Deactivate user account'
                                : 'Activate user account'
                            }
                            className={`px-2.5 py-1.5 rounded-lg text-[11px] font-medium border transition-colors flex items-center gap-1.5 ${
                              isSelf
                                ? 'opacity-40 cursor-not-allowed bg-gray-900 border-gray-800 text-gray-500'
                                : u.is_active
                                ? 'bg-red-950/20 hover:bg-red-900/40 text-red-300 border-red-800/40'
                                : 'bg-emerald-950/20 hover:bg-emerald-900/40 text-emerald-300 border-emerald-800/40'
                            }`}
                          >
                            {u.is_active ? (
                              <>
                                <UserX className="w-3 h-3 text-red-400" />
                                <span>Deactivate</span>
                              </>
                            ) : (
                              <>
                                <UserCheck className="w-3 h-3 text-emerald-400" />
                                <span>Activate</span>
                              </>
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Role Change Confirmation Modal */}
      {roleModalUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-md glass-panel p-6 rounded-2xl border border-gray-800 shadow-2xl space-y-4">
            <div className="flex items-center gap-3">
              <div
                className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border ${
                  targetRole === 'admin'
                    ? 'bg-purple-500/10 border-purple-500/20 text-purple-400'
                    : 'bg-amber-500/10 border-amber-500/20 text-amber-400'
                }`}
              >
                <Shield className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Confirm Role Change</h3>
                <p className="text-[11px] text-gray-400">
                  {targetRole === 'admin' ? 'Promote to Administrator' : 'Demote to Standard User'}
                </p>
              </div>
            </div>

            <p className="text-xs text-gray-300 leading-relaxed">
              Are you sure you want to change the role of{' '}
              <span className="font-semibold text-white">{roleModalUser.email}</span> to{' '}
              <span
                className={`font-semibold uppercase ${
                  targetRole === 'admin' ? 'text-purple-400' : 'text-blue-400'
                }`}
              >
                {targetRole}
              </span>
              ?
            </p>

            {targetRole === 'user' && (
              <p className="text-[11px] text-amber-300/80 bg-amber-500/10 p-2.5 rounded-lg border border-amber-500/20">
                This user will immediately lose access to administrator functions and document management.
              </p>
            )}

            <div className="flex justify-end gap-2 pt-2 border-t border-gray-800">
              <button
                type="button"
                onClick={() => setRoleModalUser(null)}
                disabled={isUpdatingRole}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmRoleChange}
                disabled={isUpdatingRole}
                className={`px-4 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 transition-colors ${
                  targetRole === 'admin'
                    ? 'bg-purple-600 hover:bg-purple-500 text-white shadow-lg shadow-purple-600/20'
                    : 'bg-amber-600 hover:bg-amber-500 text-white shadow-lg shadow-amber-600/20'
                }`}
              >
                {isUpdatingRole ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Updating...</span>
                  </>
                ) : (
                  <span>Confirm Change</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Status (Activate / Deactivate) Confirmation Modal */}
      {statusModalUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-md glass-panel p-6 rounded-2xl border border-gray-800 shadow-2xl space-y-4">
            <div className="flex items-center gap-3">
              <div
                className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border ${
                  targetStatus
                    ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                    : 'bg-red-500/10 border-red-500/20 text-red-400'
                }`}
              >
                {targetStatus ? <UserCheck className="w-5 h-5" /> : <UserX className="w-5 h-5" />}
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">
                  {targetStatus ? 'Activate User Account' : 'Deactivate User Account'}
                </h3>
                <p className="text-[11px] text-gray-400">{statusModalUser.email}</p>
              </div>
            </div>

            <p className="text-xs text-gray-300 leading-relaxed">
              Are you sure you want to {targetStatus ? 'activate' : 'deactivate'} the account for{' '}
              <span className="font-semibold text-white">{statusModalUser.email}</span>?
            </p>

            {!targetStatus && (
              <p className="text-[11px] text-red-300/80 bg-red-500/10 p-2.5 rounded-lg border border-red-500/20">
                Deactivation takes effect immediately. The user’s refresh tokens will be revoked and
                any ongoing sessions will be terminated on their next request.
              </p>
            )}

            <div className="flex justify-end gap-2 pt-2 border-t border-gray-800">
              <button
                type="button"
                onClick={() => setStatusModalUser(null)}
                disabled={isUpdatingStatus}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmStatusChange}
                disabled={isUpdatingStatus}
                className={`px-4 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 transition-colors ${
                  targetStatus
                    ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/20'
                    : 'bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-600/20'
                }`}
              >
                {isUpdatingStatus ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Updating...</span>
                  </>
                ) : (
                  <span>{targetStatus ? 'Activate Account' : 'Deactivate Account'}</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
