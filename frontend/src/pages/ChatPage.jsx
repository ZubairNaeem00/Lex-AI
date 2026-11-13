import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Send, Scale, Sparkles, FileText, Brain, LayoutTemplate,
  Bot, User,
  Paperclip, Pencil, Loader2, LogOut, Mic, Square, Volume2, MoreVertical, Pin, Trash2,
} from 'lucide-react';
import {
  ensureCase, getCase, listCases, sendChat, analyzeDocument,
  cancelGeneration, retryGeneration,
  clearSession, clearStoredCaseId, deleteCase, logoutRequest,
  resetCasePromise, storeCaseId, updateCase,
} from '../api/client';
import AccountSection from '../components/account/AccountSection';
import AnalyzeModal from '../components/chat/AnalyzeModal';
import AnalysisCard from '../components/chat/AnalysisCard';
import ConfirmDialog from '../components/chat/ConfirmDialog';
import DraftViewer from '../components/chat/DraftViewer';
import GenerationCard from '../components/chat/GenerationCard';
import ReviewFieldsModal from '../components/chat/ReviewFieldsModal';

const QUICK_PROMPTS = [
  'Generate a bail application',
  'Which PPC sections apply?',
  'Summarize this case',
  'Find similar precedents',
];

const GREETING = {
  role: 'ai',
  text: "Assalam o Alaikum! I'm **LexAI**, your AI legal assistant for Pakistan. I've loaded your uploaded documents and the complete PPC/CrPC database.\n\nI can help with **statute identification**, **precedent retrieval**, **document summarization**, and **draft generation**. Use the **Document Analysis** button to extract and analyse a case document — corrections you save feed every later answer and draft.",
  time: 'Just now',
};

const GREETING_EVENTS = [{ type: 'message', role: 'ai', text: GREETING.text, time: 'Just now', _greeting: true }];

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

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

export default function ChatPage() {
  const navigate = useNavigate();
  const [session, setSession] = useState(null);
  const [caseId, setCaseId] = useState(null);
  const [casesList, setCasesList] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [chatError, setChatError] = useState(null);
  const [analyzeOpen, setAnalyzeOpen] = useState(false);
  const [reviewTarget, setReviewTarget] = useState(null);
  const [sessionError, setSessionError] = useState(null);
  const [recording, setRecording] = useState(false);
  const [micInterim, setMicInterim] = useState('');
  const [micError, setMicError] = useState('');
  const [speakingKey, setSpeakingKey] = useState(null);
  const [menuFor, setMenuFor] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [renaming, setRenaming] = useState(null);
  const [signOutOpen, setSignOutOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [viewer, setViewer] = useState(null);
  const messagesEndRef = useRef(null);
  const recognitionRef = useRef(null);
  const micBufferRef = useRef('');

  const handleSignOut = async () => {
    setSigningOut(true);
    // A conversation the lawyer never wrote in should not outlive the session.
    if (caseId && isBlankSession(session)) {
      await deleteCase(caseId, true).catch(() => {});
    }
    try {
      await logoutRequest();
    } catch (e) {
      /* the tokens are cleared either way */
    }
    clearSession();
    clearStoredCaseId();
    resetCasePromise();
    setSigningOut(false);
    setSignOutOpen(false);
    navigate('/login', { state: { notice: 'You are signed out. Sign in to continue.' } });
  };

  useEffect(() => () => {
    recognitionRef.current?.abort();
    window.speechSynthesis?.cancel();
  }, []);

  const toggleMic = () => {
    if (recording) {
      recognitionRef.current?.stop();
      return;
    }
    setMicError('');
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setMicError('Voice input is not supported in this browser — use Chrome or Edge.');
      return;
    }
    const rec = new SR();
    rec.lang = navigator.language || 'en-US';
    rec.continuous = true;
    rec.interimResults = true;
    micBufferRef.current = '';
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) micBufferRef.current += `${r[0].transcript} `;
        else interim += r[0].transcript;
      }
      setMicInterim(interim);
    };
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        setMicError('Microphone access was denied. Allow it in the browser settings and try again.');
      } else if (e.error !== 'aborted' && e.error !== 'no-speech') {
        setMicError(`Voice input failed (${e.error}).`);
      }
    };
    rec.onend = () => {
      setRecording(false);
      setMicInterim('');
      const text = micBufferRef.current.trim();
      micBufferRef.current = '';
      recognitionRef.current = null;
      if (text) setInput((prev) => (prev.trim() ? `${prev.trimEnd()} ${text}` : text));
    };
    recognitionRef.current = rec;
    rec.start();
    setRecording(true);
  };

  const toggleSpeech = (key, text) => {
    const synth = window.speechSynthesis;
    if (!synth || typeof SpeechSynthesisUtterance === 'undefined') {
      setMicError('Speech playback is not supported in this browser.');
      return;
    }
    if (speakingKey === key) {
      synth.cancel();
      setSpeakingKey(null);
      return;
    }
    synth.cancel();
    const plain = String(text).replace(/\*\*/g, '').replace(/\s+/g, ' ').trim();
    if (!plain) return;
    const utterance = new SpeechSynthesisUtterance(plain);
    utterance.lang = 'en-US';
    const done = () => setSpeakingKey((k) => (k === key ? null : k));
    utterance.onend = done;
    utterance.onerror = done;
    setSpeakingKey(key);
    synth.speak(utterance);
  };

  const refresh = useCallback(async (id = caseId) => {
    if (!id) return;
    try {
      const snap = await getCase(id);
      setSession(snap);
      setCaseId(snap.case_id);
    } catch {
      /* transient — next refresh will recover */
    }
  }, [caseId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const id = await ensureCase();
        if (cancelled) return;
        setCaseId(id);
        const snap = await getCase(id);
        if (!cancelled) setSession(snap);
      } catch (e) {
        if (!cancelled) setSessionError(e.message || 'Could not reach the LegalLens backend. Start it with: uvicorn main:app --port 8000');
      }
    })();
    listCases().then((r) => setCasesList(r.sessions || [])).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [session, sending, analyzing]);

  const items = useMemo(() => {
    if (!session) return [];
    const list = [];
    const analysisPositions = new Map();
    const generationPositions = new Map();
    for (const ev of session.events || []) {
      if (ev.type === 'message') {
        if (ev.hidden) continue;
        list.push({
          kind: 'message',
          role: ev.role === 'user' ? 'user' : 'ai',
          text: ev.content || '',
          sources: ev.sources || [],
          time: fmtTime(ev.ts || ev.timestamp),
          key: `m-${ev.ts || ev.timestamp}-${list.length}`,
        });
      } else if (ev.type === 'analysis' || ev.type === 'analysis_edited') {
        if (!analysisPositions.has(ev.document_id)) {
          analysisPositions.set(ev.document_id, list.length);
          list.push({ kind: 'analysis', docId: ev.document_id, key: `a-${ev.document_id}` });
        }
      } else if (ev.type === 'generation' && ev.generation?.id) {
        const item = { kind: 'generation', gen: ev.generation, key: `g-${ev.generation.id}` };
        const position = generationPositions.get(ev.generation.id);
        if (position === undefined) {
          generationPositions.set(ev.generation.id, list.length);
          list.push(item);
        } else {
          list[position] = item;
        }
      }
    }
    return list.length ? list : GREETING_EVENTS.map((g, i) => ({ ...g, key: `greet-${i}` }));
  }, [session]);

  const send = async () => {
    const message = input.trim();
    const id = caseId;
    if (!message || !id || sending) return;

    const gen = session?.generation;
    const collecting = gen?.status === 'collecting' && gen.pending_field;
    if (!collecting) {
      setSession((prev) => prev && {
        ...prev,
        events: [...prev.events, { type: 'message', role: 'user', content: message, ts: new Date().toISOString() }],
      });
    }
    setInput('');
    setSending(true);
    setChatError(null);
    try {
      const res = await sendChat(id, message);
      await getCase(id).then(setSession).catch(() => {});
      reloadCases();
      if (res?.kind === 'generation') {
        const g = res.generation;
        if (g?.status === 'review') setReviewTarget(g);
      }
    } catch (e) {
      setChatError(e.message || 'The request failed. Your case data is intact — please retry.');
    } finally {
      setSending(false);
    }
  };

  const runAnalysis = async (file) => {
    setAnalyzeOpen(false);
    setAnalyzing(true);
    setChatError(null);
    try {
      const res = await analyzeDocument(caseId, file);
      setCaseId(res.case_id);
      await refresh(res.case_id);
      reloadCases();
    } catch (e) {
      setChatError(e.message || 'Analysis failed. Your case data is intact — please try again.');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleCancel = async (gen) => {
    if (!caseId) return;
    try {
      await cancelGeneration(caseId);
      await refresh();
    } catch (e) {
      setChatError(e.message || 'Could not cancel.');
    }
  };

  const handleRetry = async (gen) => {
    if (!caseId) return;
    try {
      const res = await retryGeneration(caseId);
      await refresh();
      const g = res?.generation;
      if (g?.status === 'review') setReviewTarget(g);
    } catch (e) {
      setChatError(e.message || 'Could not retry.');
    }
  };

  const handleReviewClose = () => {
    setReviewTarget(null);
    refresh();
  };

  const reloadCases = useCallback(() => {
    listCases().then((r) => setCasesList(r.sessions || [])).catch(() => {});
  }, []);

  /** A conversation the user never wrote in — safe to reclaim on "New Conversation". */
  const isBlankSession = (snap) => {
    if (!snap) return false;
    const spoke = (snap.events || []).some(
      (ev) => ev.type === 'message' && ev.role === 'user' && String(ev.content || '').trim(),
    );
    return !spoke && !(snap.documents || []).length && !(snap.generations || []).length;
  };

  const newConversation = async () => {
    const stale = caseId;
    setMenuFor(null);
    setConfirmDelete(null);
    setRenaming(null);
    try {
      if (stale && isBlankSession(session)) {
        // The server refuses this call if anything was recorded in the meantime.
        await deleteCase(stale, true).catch(() => {});
      }
      const id = await ensureCase(true);
      setCaseId(id);
      const snap = await getCase(id);
      setSession(snap);
      setChatError(null);
      reloadCases();
    } catch (e) {
      setChatError(e.message || 'Could not start a new conversation.');
    }
  };

  const openCase = async (id) => {
    if (!id || id === caseId) return;
    setMenuFor(null);
    setConfirmDelete(null);
    try {
      const snap = await getCase(id);
      setSession(snap);
      setCaseId(id);
      storeCaseId(id);
      setChatError(null);
    } catch (e) {
      setChatError(e.message || 'Could not load that conversation.');
    }
  };

  const commitRename = async () => {
    if (!renaming) return;
    const { id } = renaming;
    const name = renaming.value.trim();
    setRenaming(null);
    if (!name) return;
    try {
      await updateCase(id, { name });
      if (id === caseId) setSession((prev) => (prev ? { ...prev, title: name } : prev));
      reloadCases();
    } catch (e) {
      setChatError(e.message || 'Could not rename this conversation.');
    }
  };

  const togglePin = async (conversation) => {
    setMenuFor(null);
    try {
      await updateCase(conversation.case_id, { pinned: !conversation.pinned });
      reloadCases();
    } catch (e) {
      setChatError(e.message || 'Could not update this conversation.');
    }
  };

  const removeCase = async (conversation) => {
    setMenuFor(null);
    setConfirmDelete(null);
    try {
      await deleteCase(conversation.case_id);
      if (conversation.case_id === caseId) {
        resetCasePromise();
        clearStoredCaseId();
        setCaseId(null);
        setSession(null);
        const id = await ensureCase(true);
        setCaseId(id);
        setSession(await getCase(id));
      }
      reloadCases();
    } catch (e) {
      setChatError(e.message || 'Could not delete this conversation.');
    }
  };

  const gen = session?.generation;
  const generating = gen?.status === 'generating';
  const collecting = gen?.status === 'collecting' && gen.pending_field;
  const typingLabel = collecting
    ? 'Saving the detail…'
    : generating
      ? 'Generating your document…'
      : sending
        ? 'Thinking…'
        : null;
  const caseDocuments = session?.documents || [];

  const renderContent = (text) => {
    const escaped = String(text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const withBold = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    return withBold.split(/\n{2,}/).map((para, i) => (
      <p key={i} className="mb-3 last:mb-0 leading-relaxed" dangerouslySetInnerHTML={{ __html: para.replace(/\n/g, '<br/>') }} />
    ));
  };

  return (
    <div className="flex-1 flex h-full min-h-0 overflow-hidden bg-slate-50 text-slate-800 antialiased">

      {/* ── Sidebar navigation ── */}
      <aside className="w-[260px] flex-shrink-0 bg-white border-r border-slate-200 flex flex-col min-h-0">
        <div className="flex items-center gap-2.5 px-5 h-16 border-b border-slate-200 shrink-0">
          <div className="w-7 h-7 rounded-lg bg-green-600 text-white flex items-center justify-center text-xs font-bold">
            <Scale className="w-4 h-4" />
          </div>
          <span className="text-[15px] font-semibold tracking-tight text-slate-900">LexAI</span>
          <span className="ml-auto text-[10px] font-medium text-green-600 bg-green-50 border border-green-100 rounded-md px-1.5 py-0.5">Beta</span>
        </div>

        <div className="p-4 shrink-0">
          <button
            onClick={newConversation}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-green-600 text-white text-sm font-medium py-2.5 shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98]"
          >
            <Sparkles className="w-4 h-4" />
            New Conversation
          </button>
        </div>

        <div className="px-3 pb-2 shrink-0">
          <p className="px-2 mb-1 text-[11px] font-medium text-slate-400">Recent conversations</p>
          <div className="space-y-0.5">
            {casesList.length === 0 && <p className="px-2.5 py-1.5 text-[13px] text-slate-400">No conversations yet</p>}
            {casesList.slice(0, 8).map((c) => {
              const active = c.case_id === caseId;
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
                    onClick={() => openCase(c.case_id)}
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

        <div className="px-3 pt-3 pb-4 flex-1 min-h-0 overflow-y-auto scrollbar-light">
          <p className="px-2 mb-1 text-[11px] font-medium text-slate-400">Quick actions</p>
          <button
            onClick={() => setAnalyzeOpen(true)}
            className="w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors duration-150"
          >
            <FileText className="w-4 h-4 text-slate-400" />
            Document Analysis
          </button>
          <button className="w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors duration-150">
            <Brain className="w-4 h-4 text-slate-400" />
            Research Assistant
          </button>
          <button className="w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors duration-150">
            <LayoutTemplate className="w-4 h-4 text-slate-400" />
            Draft Studio
          </button>
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
      </aside>

      {/* ── Main chat ── */}
      <main className="flex-1 flex flex-col min-w-0 min-h-0">
        <header className="h-16 flex-shrink-0 flex items-center justify-between px-6 md:px-8 bg-white/80 backdrop-blur border-b border-slate-200">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="text-[15px] font-semibold text-slate-900 truncate">{session?.title || 'Legal Assistant'}</h1>
            {caseDocuments.length > 0 && (
              <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-2 py-0.5 whitespace-nowrap">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                {caseDocuments.length} document{caseDocuments.length === 1 ? '' : 's'}
              </span>
            )}
            {collecting && (
              <span className="inline-flex items-center gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-full px-2 py-0.5 whitespace-nowrap">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                Answering: {gen.pending_field.label}
              </span>
            )}
          </div>
          {session?.server_time && (
            <span className="hidden md:inline text-xs text-slate-400">Session active · {session.server_time.slice(0, 10)}</span>
          )}
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-light px-6 md:px-8 py-8" id="chat-messages">
          <div className="max-w-3xl mx-auto flex flex-col gap-6">
            {sessionError && (
              <div className="rounded-2xl bg-rose-50 border border-rose-200 p-5">
                <p className="text-rose-700 text-sm font-medium">{sessionError}</p>
              </div>
            )}

            {items.map((item) => {
              if (item.kind === 'analysis') {
                const doc = caseDocuments.find((d) => d.document_id === item.docId);
                if (!doc) return null;
                return (
                  <div key={item.key}>
                    <AnalysisCard caseId={caseId} document={doc} onSaved={() => refresh()} />
                  </div>
                );
              }
              if (item.kind === 'generation') {
                return (
                  <div key={item.key}>
                    <GenerationCard
                      caseId={caseId}
                      generation={item.gen}
                      onEdit={(genId) => setReviewTarget({ id: genId })}
                      onCancel={handleCancel}
                      onRetry={handleRetry}
                      onView={(draft) => setViewer(draft)}
                    />
                  </div>
                );
              }
              const isUser = item.role === 'user';
              return (
                <div key={item.key} className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 border
                    ${isUser ? 'bg-slate-100 border-slate-200 text-slate-500' : 'bg-green-50 border-green-100 text-green-600'}`}>
                    {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                  </div>
                  <div className={`max-w-[85%] ${isUser ? 'text-right' : ''}`}>
                    <div className={`inline-block px-4 py-3 rounded-2xl text-left text-[14px] leading-relaxed
                      ${isUser
                        ? 'bg-green-600 text-white rounded-tr-md shadow-sm'
                        : 'bg-white text-slate-700 rounded-tl-md border border-slate-200 shadow-sm'}`}>
                      {renderContent(item.text)}
                    </div>
                    {!isUser && (item.sources || []).length > 0 && (
                      <details className="mt-2 group text-left">
                        <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-[11px] font-medium text-green-700">
                          <Scale className="w-3.5 h-3.5" />
                          Retrieved sources ({item.sources.length})
                        </summary>
                        <ul className="mt-1.5 space-y-1 rounded-xl bg-white border border-slate-200 p-3">
                          {item.sources.map((s, i) => (
                            <li key={i} className="text-[11px] text-slate-500 leading-relaxed">{s}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                    <div className={`mt-1.5 px-1 flex items-center gap-2 ${isUser ? 'justify-end' : ''}`}>
                      {!isUser && (
                        <button
                          onClick={() => toggleSpeech(item.key, item.text)}
                          title={speakingKey === item.key ? 'Stop speech' : 'Read this answer aloud'}
                          className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium transition-colors duration-150
                            ${speakingKey === item.key
                              ? 'text-rose-600 bg-rose-50'
                              : 'text-slate-400 hover:text-green-700 hover:bg-green-50'}`}
                        >
                          {speakingKey === item.key ? <Square className="w-3 h-3" /> : <Volume2 className="w-3 h-3" />}
                          {speakingKey === item.key ? 'Stop' : 'Listen'}
                        </button>
                      )}
                      {item.time && <p className="text-[11px] text-slate-400">{item.time}</p>}
                    </div>
                  </div>
                </div>
              );
            })}

            {chatError && (
              <div className="rounded-2xl bg-rose-50 border border-rose-200 p-5">
                <p className="text-rose-700 text-sm font-medium">{chatError}</p>
              </div>
            )}

            {typingLabel && (
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-full bg-green-50 border border-green-100 text-green-600 flex items-center justify-center shrink-0">
                  <Loader2 className="w-4 h-4 animate-spin" />
                </div>
                <div className="bg-white px-4 py-3 rounded-2xl rounded-tl-md border border-slate-200 shadow-sm">
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-300 animate-bounce" />
                    <span className="w-1.5 h-1.5 rounded-full bg-green-300 animate-bounce" style={{ animationDelay: '0.2s' }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-green-300 animate-bounce" style={{ animationDelay: '0.4s' }} />
                  </div>
                  <p className="text-slate-500 text-[13px] mt-2">{typingLabel}</p>
                </div>
              </div>
            )}

            {analyzing && (
              <div className="rounded-2xl bg-white border border-slate-200 p-5 shadow-sm">
                <div className="flex items-center gap-3 mb-2">
                  <Loader2 className="w-4 h-4 text-green-600 animate-spin" />
                  <p className="text-slate-900 text-sm font-medium">Analysing document…</p>
                </div>
                <p className="text-slate-500 text-[13px] leading-relaxed">LlamaParse is extracting the text (Urdu/English OCR), then the structured report is built. This can take up to a minute.</p>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        <div className="px-6 md:px-8 pb-6 pt-2 shrink-0 bg-slate-50">
          <div className="max-w-3xl mx-auto flex flex-col gap-3">
            <div className="flex gap-2 flex-wrap">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => setInput(prompt)}
                  className="rounded-full border border-slate-200 bg-white px-3.5 py-1.5 text-xs font-medium text-slate-600 shadow-sm transition-all duration-200 hover:border-green-300 hover:bg-green-50 hover:text-green-700"
                >
                  {prompt}
                </button>
              ))}
            </div>
            <div>
              {(recording || micError) && (
                <div className="mb-2 flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-[12px] shadow-sm">
                  {recording ? (
                    <>
                      <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse shrink-0" />
                      <span className="min-w-0 truncate text-slate-600">
                        Listening… {micInterim ? `“${micInterim}”` : 'speak now, then click the mic to stop'}
                      </span>
                    </>
                  ) : (
                    <span className="text-rose-600">{micError}</span>
                  )}
                </div>
              )}
              <div className="flex items-end gap-3 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm transition-all duration-200 focus-within:border-green-300 focus-within:ring-4 focus-within:ring-green-100">
                <button
                  onClick={() => setAnalyzeOpen(true)}
                  title="Upload & analyse a document"
                  className="shrink-0 rounded-xl p-2.5 text-slate-400 transition-colors duration-200 hover:bg-green-50 hover:text-green-600"
                >
                  <Paperclip className="w-5 h-5" />
                </button>
                <button
                  onClick={toggleMic}
                  title={recording ? 'Stop recording and add the text' : 'Dictate your message'}
                  aria-pressed={recording}
                  className={`shrink-0 rounded-xl p-2.5 transition-colors duration-200
                    ${recording
                      ? 'bg-rose-50 text-rose-600 animate-pulse'
                      : 'text-slate-400 hover:bg-green-50 hover:text-green-600'}`}
                >
                  <Mic className="w-5 h-5" />
                </button>
                <textarea
                  rows={Math.min(6, Math.max(1, input.split('\n').length))}
                  placeholder={collecting ? `Answer: ${gen?.pending_field?.label || 'the question above'}…` : generating ? 'Document generation is in progress…' : 'Ask about PPC statutes, precedents, or case strategy…'}
                  className="flex-1 resize-none bg-transparent py-2.5 text-[15px] text-slate-800 placeholder:text-slate-400 focus:outline-none max-h-48 overflow-y-auto scrollbar-light"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                  disabled={!caseId}
                />
                <button
                  onClick={send}
                  disabled={sending || generating || !input.trim() || !caseId}
                  className="shrink-0 inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2.5 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Send className="w-4 h-4" />
                  Send
                </button>
              </div>
              <p className="mt-2.5 text-center text-[11px] text-slate-400">
                LexAI can make mistakes — verify important legal information with qualified counsel.
              </p>
            </div>
          </div>
        </div>
      </main>

      {viewer && caseId && (
        <DraftViewer
          caseId={caseId}
          draft={viewer}
          onClose={() => setViewer(null)}
          onSaved={() => refresh()}
        />
      )}

      <AnalyzeModal
        open={analyzeOpen}
        busy={analyzing}
        onClose={() => !analyzing && setAnalyzeOpen(false)}
        onAnalyze={runAnalysis}
      />

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

      {reviewTarget && (
        <ReviewFieldsModal
          caseId={caseId}
          generationId={reviewTarget.id}
          onClose={handleReviewClose}
          onSaved={() => refresh()}
        />
      )}
    </div>
  );
}
