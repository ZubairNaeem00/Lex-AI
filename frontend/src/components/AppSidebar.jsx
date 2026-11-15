import React, { forwardRef, useEffect, useImperativeHandle, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Scale, Sparkles, FileText, LayoutTemplate, MessageSquare, BarChart3,
  Pencil, MoreVertical, Pin, Trash2, LogOut, Bookmark,
} from 'lucide-react';
import {
  listCases, updateCase, deleteCase, logoutRequest,
  clearSession, clearStoredCaseId, resetCasePromise,
} from '../api/client';
import AccountSection from './account/AccountSection';
import ConfirmDialog from './chat/ConfirmDialog';
import SavedCasesModal from './chat/SavedCasesModal';
import { useSavedCases } from '../savedCases';

const MenuItem = ({ icon: RowIcon, label, onClick, danger }) => (
  <button
    onClick={onClick}
    className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[13px] transition-colors ${danger
      ? 'text-rose-600 hover:bg-rose-50'
      : 'text-slate-700 hover:bg-slate-100'}`}
  >
    <RowIcon className="w-3.5 h-3.5 shrink-0" />
    {label}
  </button>
);

const WORKSPACE_NAV = [
  { label: 'Assistant', icon: MessageSquare, to: '/chat' },
  { label: 'Reports', icon: BarChart3, to: '/reports' },
];

/* The single application sidebar, shared by the chat, upload and reports pages.
   Conversation list + CRUD and the account/sign-out flow live here; the host page
   supplies what should happen when a conversation is opened, created or removed. */
const AppSidebar = forwardRef(function AppSidebar({
  activeCaseId = null,
  onOpenCase,
  onNewConversation,
  onActiveCaseRemoved,
  onActiveCaseRenamed,
  onBeforeSignOut,
}, ref) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [casesList, setCasesList] = useState([]);
  const [menuFor, setMenuFor] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [renaming, setRenaming] = useState(null);
  const [signOutOpen, setSignOutOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [savedOpen, setSavedOpen] = useState(false);
  const savedCount = useSavedCases().length;

  const reload = () => {
    listCases().then((r) => setCasesList(r.sessions || [])).catch(() => {});
  };

  useImperativeHandle(ref, () => ({ reload }), []);
  useEffect(reload, []);

  const commitRename = async () => {
    if (!renaming) return;
    const { id } = renaming;
    const name = renaming.value.trim();
    setRenaming(null);
    if (!name) return;
    try {
      await updateCase(id, { name });
      if (id === activeCaseId) onActiveCaseRenamed?.(name);
      reload();
    } catch (e) {
      /* keep the previous title on failure */
    }
  };

  const togglePin = async (conversation) => {
    setMenuFor(null);
    try {
      await updateCase(conversation.case_id, { pinned: !conversation.pinned });
      reload();
    } catch (e) {
      /* leave pin state unchanged on failure */
    }
  };

  const removeCase = async (conversation) => {
    setMenuFor(null);
    setConfirmDelete(null);
    try {
      await deleteCase(conversation.case_id);
      if (conversation.case_id === activeCaseId) await onActiveCaseRemoved?.();
      reload();
    } catch (e) {
      /* conversation stays listed on failure */
    }
  };

  const startNewConversation = async () => {
    setMenuFor(null);
    setConfirmDelete(null);
    setRenaming(null);
    try {
      await onNewConversation?.();
      reload();
    } catch (e) {
      /* host surfaces the error */
    }
  };

  const handleSignOut = async () => {
    setSigningOut(true);
    try { await onBeforeSignOut?.(); } catch (e) { /* proceed with sign-out */ }
    try { await logoutRequest(); } catch (e) { /* tokens are cleared either way */ }
    clearSession();
    clearStoredCaseId();
    resetCasePromise();
    setSigningOut(false);
    setSignOutOpen(false);
    navigate('/login', { state: { notice: 'You are signed out. Sign in to continue.' } });
  };

  return (
    <aside className="w-[260px] flex-shrink-0 bg-white border-r border-slate-200 flex flex-col min-h-0">
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-slate-200 shrink-0">
        <div className="w-7 h-7 rounded-lg bg-green-600 text-white flex items-center justify-center text-xs font-bold">
          <Scale className="w-4 h-4" />
        </div>
        <span className="text-[15px] font-semibold tracking-tight text-slate-900">LexAI</span>
        <span className="ml-auto text-[10px] font-medium text-green-600 bg-green-50 border border-green-100 rounded-md px-1.5 py-0.5">Beta</span>
      </div>

      <div className="p-4 pb-2 shrink-0">
        <button
          onClick={startNewConversation}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-green-600 text-white text-sm font-medium py-2.5 shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98]"
        >
          <Sparkles className="w-4 h-4" />
          New Conversation
        </button>
      </div>

      <div className="px-3 pb-2 shrink-0">
        <p className="px-2 mb-1 text-[11px] font-medium text-slate-400">Workspace</p>
        {WORKSPACE_NAV.map((item) => {
          const active = pathname === item.to;
          return (
            <button
              key={item.label}
              onClick={() => navigate(item.to)}
              className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm transition-colors duration-150
                ${active ? 'bg-slate-100 text-slate-900 font-medium' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'}`}
            >
              <item.icon className={`w-4 h-4 ${active ? 'text-green-600' : 'text-slate-400'}`} />
              {item.label}
            </button>
          );
        })}
      </div>

      <div className="px-3 pb-2 shrink-0">
        <button
          onClick={() => setSavedOpen(true)}
          className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm transition-colors duration-150
            ${savedOpen ? 'bg-slate-100 text-slate-900 font-medium' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'}`}
        >
          <Bookmark className={`w-4 h-4 ${savedOpen ? 'text-green-600' : 'text-slate-400'}`} />
          Saved cases
          {savedCount > 0 && (
            <span className="ml-auto rounded-md bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold text-green-700">
              {savedCount}
            </span>
          )}
        </button>
        <button
          onClick={() => navigate('/upload')}
          className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm transition-colors duration-150
            ${pathname === '/upload' ? 'bg-slate-100 text-slate-900 font-medium' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'}`}
        >
          <FileText className={`w-4 h-4 ${pathname === '/upload' ? 'text-green-600' : 'text-slate-400'}`} />
          Document Analysis
        </button>
        <button className="w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors duration-150">
          <LayoutTemplate className="w-4 h-4 text-slate-400" />
          Draft Studio
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-light px-3 pt-2 pb-4">
        <p className="px-2 mb-1 text-[11px] font-medium text-slate-400">Recent conversations</p>
        <div className="space-y-0.5">
          {casesList.length === 0 && <p className="px-2.5 py-1.5 text-[13px] text-slate-400">No conversations yet</p>}
          {casesList.slice(0, 8).map((c) => {
            const active = c.case_id === activeCaseId;
            const rowTone = active
              ? 'bg-green-50 text-green-700 font-medium'
              : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900';

            if (renaming && renaming.id === c.case_id) {
              return (
                <div key={c.case_id} className="py-1">
                  <input
                    autoFocus
                    value={renaming.value}
                    maxLength={80}
                    onChange={(e) => setRenaming({ ...renaming, value: e.target.value })}
                    onBlur={commitRename}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitRename();
                      if (e.key === 'Escape') setRenaming(null);
                    }}
                    className="w-full rounded-lg border border-green-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 outline-none focus:ring-2 focus:ring-green-100"
                  />
                </div>
              );
            }

            const menuOpen = menuFor === c.case_id;
            return (
              <div key={c.case_id} className="relative group">
                <button
                  onClick={() => onOpenCase?.(c.case_id)}
                  className={`w-full text-left flex items-center gap-1.5 px-2.5 py-2 pr-8 rounded-lg text-sm transition-colors duration-150 ${rowTone}`}
                >
                  {c.pinned && <Pin className="w-3 h-3 shrink-0 opacity-80" />}
                  <span className="block truncate">{c.title || 'Untitled case'}</span>
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmDelete(null);
                    setMenuFor(menuOpen ? null : c.case_id);
                  }}
                  aria-label={`Options for ${c.title || 'conversation'}`}
                  className={`absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 transition-opacity hover:bg-slate-200/70 hover:text-slate-600 ${menuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
                >
                  <MoreVertical className="w-4 h-4" />
                </button>

                {menuOpen && (
                  <>
                    <button
                      type="button"
                      tabIndex={-1}
                      aria-hidden="true"
                      onClick={() => { setMenuFor(null); setConfirmDelete(null); }}
                      className="fixed inset-0 z-10 cursor-default"
                    />
                    <div className="absolute right-0 top-full mt-1 z-20 w-48 rounded-xl border border-slate-200 bg-white p-1 shadow-lg shadow-slate-200/70">
                      {confirmDelete === c.case_id ? (
                        <div className="p-2">
                          <p className="text-[12px] leading-snug text-slate-600">
                            Delete this conversation and everything in it?
                          </p>
                          <div className="mt-2.5 flex gap-2">
                            <button
                              onClick={() => setConfirmDelete(null)}
                              className="flex-1 rounded-lg border border-slate-200 px-2 py-1 text-[12px] font-medium text-slate-600 hover:bg-slate-50"
                            >
                              Cancel
                            </button>
                            <button
                              onClick={() => removeCase(c)}
                              className="flex-1 rounded-lg bg-rose-600 px-2 py-1 text-[12px] font-medium text-white hover:bg-rose-700"
                            >
                              Delete
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <MenuItem
                            icon={Pencil}
                            label="Rename"
                            onClick={() => {
                              setMenuFor(null);
                              setRenaming({ id: c.case_id, value: c.title || '' });
                            }}
                          />
                          <MenuItem
                            icon={Pin}
                            label={c.pinned ? 'Unpin' : 'Pin to top'}
                            onClick={() => togglePin(c)}
                          />
                          <MenuItem
                            icon={Trash2}
                            label="Delete"
                            danger
                            onClick={() => setConfirmDelete(c.case_id)}
                          />
                        </>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="p-4 border-t border-slate-200 shrink-0 space-y-3">
        <div className="flex items-start gap-2.5 rounded-xl bg-slate-50 border border-slate-100 p-3">
          <Sparkles className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-slate-900 leading-tight">Premium Access</p>
            <p className="text-[11px] text-slate-500 mt-0.5">Unlimited cases &amp; exports</p>
          </div>
        </div>

        <AccountSection onLogout={() => setSignOutOpen(true)} />
      </div>

      {signOutOpen && (
        <ConfirmDialog
          title="Sign out of LexAI?"
          message="Conversations you have started stay in your account. An empty one will be discarded."
          confirmLabel="Sign out"
          cancelLabel="Stay signed in"
          danger
          busy={signingOut}
          icon={<LogOut className="w-4 h-4" />}
          onConfirm={handleSignOut}
          onCancel={() => !signingOut && setSignOutOpen(false)}
        />
      )}

      <SavedCasesModal open={savedOpen} onClose={() => setSavedOpen(false)} />
    </aside>
  );
});

export default AppSidebar;