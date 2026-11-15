import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import {
  Send, Scale, Brain,
  Bot, User,
  Paperclip, Loader2, Mic, Square, Volume2,
} from 'lucide-react';
import {
  ensureCase, getCase, sendChat, analyzeDocument,
  cancelGeneration, retryGeneration,
  clearStoredCaseId, deleteCase,
  resetCasePromise, storeCaseId,
} from '../api/client';
import AppSidebar from '../components/AppSidebar';
import AnalyzeModal from '../components/chat/AnalyzeModal';
import AnalysisCard from '../components/chat/AnalysisCard';
import CaseSlider from '../components/chat/CaseSlider';
import DraftViewer from '../components/chat/DraftViewer';
import GenerationCard from '../components/chat/GenerationCard';
import ReviewFieldsModal from '../components/chat/ReviewFieldsModal';
import { LLM_PROVIDERS, getProvider, providerNote, setProvider } from '../llmProvider';

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

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

export default function ChatPage() {
  const location = useLocation();
  const [session, setSession] = useState(null);
  const [caseId, setCaseId] = useState(null);
  const [input, setInput] = useState('');
  const [provider, setProviderChoice] = useState(getProvider);
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
  const [viewer, setViewer] = useState(null);
  const messagesEndRef = useRef(null);
  const recognitionRef = useRef(null);
  const micBufferRef = useRef('');
  const sidebarRef = useRef(null);

  /* A conversation the lawyer never wrote in should not outlive the session. */
  const reclaimBlankActive = async () => {
    if (caseId && isBlankSession(session)) {
      await deleteCase(caseId, true).catch(() => {});
    }
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
        if (!cancelled && location.state?.prefill) setInput(location.state.prefill);
      } catch (e) {
        if (!cancelled) setSessionError(e.message || 'Could not reach the LegalLens backend. Start it with: uvicorn main:app --port 8000');
      }
    })();
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
        if (ev.kind === 'case_retrieval' && ev.retrieval) {
          list.push({ kind: 'cases', retrieval: ev.retrieval, key: `c-${ev.ts}-${list.length}` });
          continue;
        }
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

  const chooseProvider = (key) => setProviderChoice(setProvider(key));

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
      const res = await sendChat(id, message, provider);
      await getCase(id).then(setSession).catch(() => {});
      sidebarRef.current?.reload();
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
      sidebarRef.current?.reload();
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
    } catch (e) {
      setChatError(e.message || 'Could not start a new conversation.');
    }
  };

  const openCase = async (id) => {
    if (!id || id === caseId) return;
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

  const handleActiveCaseRemoved = async () => {
    resetCasePromise();
    clearStoredCaseId();
    setCaseId(null);
    setSession(null);
    const id = await ensureCase(true);
    setCaseId(id);
    setSession(await getCase(id));
  };

  const handleActiveCaseRenamed = (name) => {
    setSession((prev) => (prev ? { ...prev, title: name } : prev));
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

      {/* ── Shared application sidebar ── */}
      <AppSidebar
        ref={sidebarRef}
        activeCaseId={caseId}
        onOpenCase={openCase}
        onNewConversation={newConversation}
        onActiveCaseRemoved={handleActiveCaseRemoved}
        onActiveCaseRenamed={handleActiveCaseRenamed}
        onBeforeSignOut={reclaimBlankActive}
      />

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
              if (item.kind === 'cases') {
                return (
                  <div key={item.key}>
                    <CaseSlider retrieval={item.retrieval} />
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
              <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm transition-all duration-200 focus-within:border-green-300 focus-within:ring-4 focus-within:ring-green-100">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2">
                  <label className="flex items-center gap-2 text-[11px] font-medium text-slate-500">
                    <Brain className="h-3.5 w-3.5 text-slate-400" />
                    Answer model
                    <select
                      value={provider}
                      onChange={(e) => chooseProvider(e.target.value)}
                      disabled={sending || generating}
                      title="Only legal chat answers use this model. Document analysis and generation always use Groq."
                      className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-700 shadow-sm outline-none transition-colors duration-200 hover:border-green-300 focus:border-green-400 focus:ring-2 focus:ring-green-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {LLM_PROVIDERS.map((option) => (
                        <option key={option.key} value={option.key}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <span className="text-[11px] text-slate-500">{providerNote(provider)}</span>
                </div>
                <div className="flex items-end gap-3">
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
