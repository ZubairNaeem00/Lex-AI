import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, Download, Italic,
  Loader2, Redo2, Save, Strikethrough, Underline, Undo2, X,
} from 'lucide-react';
import { downloadGeneratedDocument, getDraftDocument, saveDraftDocument } from '../../api/client';

const SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 22, 24, 28];

const ToolButton = ({ icon: Icon, label, onPress, active, disabled }) => (
  <button
    type="button"
    title={label}
    aria-label={label}
    aria-pressed={!!active}
    disabled={disabled}
    onMouseDown={(event) => event.preventDefault()}
    onClick={onPress}
    className={`shrink-0 rounded-lg p-1.5 transition-colors duration-150 disabled:opacity-40
      ${active
        ? 'bg-green-600 text-white shadow-sm'
        : 'text-slate-600 hover:bg-green-50 hover:text-green-700'}`}
  >
    <Icon className="h-4 w-4" />
  </button>
);

const Divider = () => <span className="mx-0.5 h-5 w-px shrink-0 bg-slate-200" />;

/** Side panel that shows a generated draft as a Word-style page and saves edits
    back as a new DOCX revision. */
export default function DraftViewer({ caseId, draft, onClose, onSaved }) {
  const [document_, setDocument] = useState(null);
  const [markup, setMarkup] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [askDiscard, setAskDiscard] = useState(false);
  const [marks, setMarks] = useState({});
  const pageRef = useRef(null);
  const scrollRef = useRef(null);
  const rangeRef = useRef(null);
  const generationId = draft.generationId;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    getDraftDocument(caseId, generationId)
      .then((payload) => {
        if (cancelled) return;
        setDocument(payload);
        setMarkup(payload.editable ? payload.html : '');
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message || 'This draft could not be opened for editing.');
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [caseId, generationId]);

  /* The page is uncontrolled once loaded, so markup is written into the DOM
     directly — on open and again after a save, whose response carries the
     paragraph references of the new revision. */
  useEffect(() => {
    const page = pageRef.current;
    if (!page || !markup) return;
    const top = scrollRef.current ? scrollRef.current.scrollTop : 0;
    page.innerHTML = markup;
    if (scrollRef.current) scrollRef.current.scrollTop = top;
  }, [markup]);

  useEffect(() => {
    const onSelect = () => {
      const page = pageRef.current;
      const selection = window.getSelection();
      if (!page || !selection || !selection.rangeCount) return;
      const range = selection.getRangeAt(0);
      if (!page.contains(range.commonAncestorContainer)) return;
      rangeRef.current = range.cloneRange();
      const state = (command) => {
        try { return document.queryCommandState(command); } catch { return false; }
      };
      setMarks({
        bold: state('bold'),
        italic: state('italic'),
        underline: state('underline'),
        strikeThrough: state('strikeThrough'),
        justifyLeft: state('justifyLeft'),
        justifyCenter: state('justifyCenter'),
        justifyRight: state('justifyRight'),
        justifyFull: state('justifyFull'),
      });
    };
    document.addEventListener('selectionchange', onSelect);
    return () => document.removeEventListener('selectionchange', onSelect);
  }, []);

  const restoreSelection = useCallback(() => {
    const page = pageRef.current;
    if (!page) return false;
    const saved = rangeRef.current;
    if (saved && (!window.getSelection().rangeCount || !page.contains(window.getSelection().getRangeAt(0).commonAncestorContainer))) {
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(saved);
    }
    page.focus();
    return true;
  }, []);

  const run = useCallback((command, value = null) => {
    if (!restoreSelection()) return;
    try {
      document.execCommand(command, false, value);
      setDirty(true);
    } catch {
      setError('That formatting change is not supported by this browser.');
    }
  }, [restoreSelection]);

  /* Browsers only offer the seven <font size> steps, so the placeholder size is
     swapped for the exact point size the advocate picked. */
  const applySize = useCallback((points) => {
    const page = pageRef.current;
    if (!page || !restoreSelection()) return;
    document.execCommand('styleWithCSS', false, false);
    document.execCommand('fontSize', false, '7');
    page.querySelectorAll('font[size="7"]').forEach((font) => {
      const span = document.createElement('span');
      span.style.fontSize = `${points}pt`;
      while (font.firstChild) span.appendChild(font.firstChild);
      font.replaceWith(span);
    });
    page.querySelectorAll('[style*="xxx-large"]').forEach((element) => {
      element.style.fontSize = `${points}pt`;
    });
    setDirty(true);
  }, [restoreSelection]);

  const handleSave = useCallback(async () => {
    const page = pageRef.current;
    if (!page || saving) return;
    setSaving(true);
    setError('');
    try {
      const result = await saveDraftDocument(caseId, generationId, page.innerHTML);
      const payload = result.document || {};
      setDocument(payload);
      setMarkup(payload.html || '');
      setDirty(false);
      setSavedAt(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      if (onSaved) onSaved();
    } catch (err) {
      setError(err.message || 'The revised draft could not be saved. Your edits are still here.');
    } finally {
      setSaving(false);
    }
  }, [caseId, generationId, onSaved, saving]);

  const handleDownload = useCallback(async () => {
    const match = /\/sessions\/([^/]+)\/download\/(.+)$/.exec((document_ && document_.download_url) || '');
    const target = match
      ? { case: decodeURIComponent(match[1]), filename: decodeURIComponent(match[2]) }
      : { case: caseId, filename: document_ && document_.filename };
    if (!target.filename) {
      setError('This draft has no downloadable file yet.');
      return;
    }
    setDownloading(true);
    setError('');
    try {
      const blob = await downloadGeneratedDocument(target.case, target.filename);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = target.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || 'Could not download the document.');
    } finally {
      setDownloading(false);
    }
  }, [caseId, document_]);

  const requestClose = useCallback(() => {
    if (dirty) {
      setAskDiscard(true);
      return;
    }
    onClose();
  }, [dirty, onClose]);

  const saveAndClose = useCallback(async () => {
    await handleSave();
    onClose();
  }, [handleSave, onClose]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') requestClose();
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        if (dirty && !saving) handleSave();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handleSave, requestClose, dirty, saving]);

  const baseFont = (document_ && document_.base_font) || 'Times New Roman';
  const baseSize = (document_ && document_.base_size) || 12;
  const editable = !!(document_ && document_.editable);

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-slate-200 bg-slate-100 shadow-2xl
        lg:static lg:z-auto lg:w-[54%] lg:max-w-[860px] lg:shadow-none xl:w-[48%]"
      aria-label="Draft editor"
    >
      <header className="flex shrink-0 items-start gap-3 border-b border-slate-200 bg-white px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[1.5px] text-green-700">
            {document_ && document_.is_revision ? 'Revised draft' : 'Draft preview'}
          </p>
          <h3 className="mt-0.5 truncate text-[14px] font-semibold text-slate-900">
            {(document_ && document_.template_label) || draft.templateLabel || 'Legal document'}
          </h3>
          <p className="mt-0.5 truncate text-[11px] text-slate-400">
            {(document_ && document_.filename) || draft.filename || ''}
          </p>
        </div>
        <button
          type="button"
          onClick={requestClose}
          title="Close the draft"
          aria-label="Close the draft"
          className="shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors duration-150 hover:bg-slate-100 hover:text-slate-700"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      {askDiscard && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2.5 text-[12px] text-amber-800">
          <span>You have unsaved edits on this draft.</span>
          <button
            type="button"
            onClick={saveAndClose}
            className="rounded-lg bg-amber-600 px-2.5 py-1 font-medium text-white hover:bg-amber-700"
          >
            Save and close
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-amber-300 bg-white px-2.5 py-1 font-medium text-amber-800 hover:bg-amber-100"
          >
            Discard
          </button>
          <button
            type="button"
            onClick={() => setAskDiscard(false)}
            className="rounded-lg px-2 py-1 font-medium text-amber-700 hover:bg-amber-100"
          >
            Keep editing
          </button>
        </div>
      )}

      {error && (
        <div className="flex shrink-0 items-start gap-2 border-b border-rose-200 bg-rose-50 px-4 py-2.5 text-[12px] leading-relaxed text-rose-700">
          <span className="min-w-0 flex-1">{error}</span>
          <button type="button" onClick={() => setError('')} className="shrink-0 font-medium hover:underline">Dismiss</button>
        </div>
      )}

      {editable && (
        <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-slate-200 bg-white px-3 py-2">
          <ToolButton icon={Undo2} label="Undo" onPress={() => run('undo')} disabled={saving} />
          <ToolButton icon={Redo2} label="Redo" onPress={() => run('redo')} disabled={saving} />
          <Divider />
          <ToolButton icon={Bold} label="Bold (Ctrl+B)" active={marks.bold} onPress={() => run('bold')} disabled={saving} />
          <ToolButton icon={Italic} label="Italic (Ctrl+I)" active={marks.italic} onPress={() => run('italic')} disabled={saving} />
          <ToolButton icon={Underline} label="Underline (Ctrl+U)" active={marks.underline} onPress={() => run('underline')} disabled={saving} />
          <ToolButton icon={Strikethrough} label="Strikethrough" active={marks.strikeThrough} onPress={() => run('strikeThrough')} disabled={saving} />
          <Divider />
          <select
            title="Font size"
            aria-label="Font size"
            value=""
            disabled={saving}
            onChange={(event) => event.target.value && applySize(Number(event.target.value))}
            className="shrink-0 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[12px] font-medium text-slate-600 outline-none transition-colors hover:border-green-300 focus:border-green-400 disabled:opacity-40"
          >
            <option value="">Size</option>
            {SIZES.map((points) => (
              <option key={points} value={points}>{points} pt</option>
            ))}
          </select>
          <Divider />
          <ToolButton icon={AlignLeft} label="Align left" active={marks.justifyLeft} onPress={() => run('justifyLeft')} disabled={saving} />
          <ToolButton icon={AlignCenter} label="Align centre" active={marks.justifyCenter} onPress={() => run('justifyCenter')} disabled={saving} />
          <ToolButton icon={AlignRight} label="Align right" active={marks.justifyRight} onPress={() => run('justifyRight')} disabled={saving} />
          <ToolButton icon={AlignJustify} label="Justify" active={marks.justifyFull} onPress={() => run('justifyFull')} disabled={saving} />
          <span className="flex-1" />
          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading || saving}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[12px] font-medium text-slate-600 transition-colors duration-150 hover:border-green-300 hover:text-green-700 disabled:opacity-50"
          >
            <Download className="h-3.5 w-3.5" />
            {downloading ? 'Preparing…' : 'DOCX'}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !dirty}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-[12px] font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 disabled:opacity-40"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {saving ? 'Saving…' : 'Save revision'}
          </button>
        </div>
      )}

      <div ref={scrollRef} className="scrollbar-light min-h-0 flex-1 overflow-y-auto bg-slate-100">
        {loading && (
          <div className="flex h-full items-center justify-center gap-2 text-[13px] text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin text-green-600" />
            Opening the draft…
          </div>
        )}

        {!loading && !editable && document_ && (
          <div className="mx-4 mt-4 rounded-2xl border border-slate-200 bg-white p-5 text-[13px] leading-relaxed text-slate-600">
            {document_.reason || 'This draft cannot be edited here.'}
            <div className="mt-3">
              <button
                type="button"
                onClick={handleDownload}
                disabled={downloading}
                className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-[13px] font-medium text-white hover:bg-green-700 disabled:opacity-60"
              >
                <Download className="h-4 w-4" />
                {downloading ? 'Preparing…' : 'Download DOCX'}
              </button>
            </div>
          </div>
        )}

        {!loading && editable && (
          <div className="draft-sheet mx-auto my-5 w-[min(794px,calc(100%-24px))] rounded-sm bg-white px-[9%] py-[68px] shadow-[0_1px_3px_rgba(15,23,42,0.14)] ring-1 ring-slate-200">
            <div
              ref={pageRef}
              className="draft-page min-h-[560px]"
              contentEditable
              suppressContentEditableWarning
              spellCheck={false}
              role="textbox"
              aria-multiline="true"
              aria-label={`Editable draft of ${draft.templateLabel || 'the document'}`}
              onInput={() => setDirty(true)}
              onPaste={(event) => {
                // Pasted markup from another app carries styles this editor cannot
                // map back into the DOCX, so only its text is kept.
                event.preventDefault();
                const text = (event.clipboardData || window.clipboardData).getData('text/plain');
                document.execCommand('insertText', false, text);
                setDirty(true);
              }}
              style={{
                fontFamily: `"${baseFont}", Georgia, serif`,
                fontSize: `${baseSize}pt`,
                lineHeight: 1.5,
                color: '#0f172a',
              }}
            />
          </div>
        )}

        {!loading && !error && (
          <p className="mx-auto mb-6 w-[min(794px,calc(100%-24px))] text-[11px] leading-relaxed text-slate-400">
            {dirty
              ? 'Unsaved edits — Save revision writes a new DOCX; the original file is kept.'
              : savedAt
                ? `Revision saved at ${savedAt}. Download serves the saved version.`
                : 'Click into the text to edit. Formatting and spacing are written back into the document.'}
          </p>
        )}
      </div>
    </aside>
  );
}
