/* Which model answers legal chat questions. Document analysis and generation
   always use Groq on the server, so this choice only affects the RAG agent. */

const STORAGE_KEY = 'lexai.llm_provider';

export const LLM_PROVIDERS = [
  { key: 'groq', label: 'Groq', note: 'Cloud model — no local install needed' },
  { key: 'ollama', label: 'Ollama', note: 'Local Qwen model — needs Ollama running' },
];

const DEFAULT_PROVIDER = 'groq';

export function getProvider() {
  const saved = localStorage.getItem(STORAGE_KEY);
  return LLM_PROVIDERS.some((provider) => provider.key === saved) ? saved : DEFAULT_PROVIDER;
}

export function setProvider(provider) {
  const next = LLM_PROVIDERS.some((item) => item.key === provider) ? provider : DEFAULT_PROVIDER;
  localStorage.setItem(STORAGE_KEY, next);
  return next;
}

export function providerNote(provider) {
  const match = LLM_PROVIDERS.find((item) => item.key === provider);
  return match ? match.note : '';
}