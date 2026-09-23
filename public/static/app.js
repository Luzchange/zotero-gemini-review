let savedModel = localStorage.getItem('zg_gemini_model');
if (savedModel === 'gemini-2.5-flash' || savedModel === 'gemini-3.6-pro') {
  savedModel = 'gemini-3.6-flash';
  localStorage.setItem('zg_gemini_model', savedModel);
}

const DEFAULT_ZOTERO_KEY = 'qoszWMinOK1os3M4T9OTQLbH';
const DEFAULT_ZOTERO_USER_ID = '5425893';

let appState = {
  activeTab: 'deep-dive',
  collections: [],
  papers: [],
  selectedKeys: new Set(),
  activePaperKey: null,
  workDocuments: [],
  activeDocumentId: null,
  lastAnalyzedDocumentId: null,
  currentReviewMarkdown: '',
  currentZoteroHtml: '',
  lastAnalyzedItemKey: null,
  chatHistory: [],
  searchTimeout: null,
  literatureResults: [],
  litSource: 'pubmed',
  credentials: {
    geminiKey: localStorage.getItem('zg_gemini_key') || '',
    geminiModel: savedModel || 'gemini-3.6-flash',
    geminiBaseUrl: localStorage.getItem('zg_gemini_base_url') || '',
    zoteroKey: localStorage.getItem('zg_zotero_key') || DEFAULT_ZOTERO_KEY,
    zoteroUserId: localStorage.getItem('zg_zotero_user_id') || DEFAULT_ZOTERO_USER_ID,
    zoteroLibType: localStorage.getItem('zg_zotero_lib_type') || 'user',
    ncbiKey: localStorage.getItem('zg_ncbi_key') || '',
    schoolProxy: localStorage.getItem('zg_school_proxy') || ''
  }
};

// Global API helper attaching custom credentials if present
async function apiFetch(url, options = {}) {
  const headers = options.headers || {};
  if (appState.credentials.geminiKey) headers['X-Gemini-Key'] = appState.credentials.geminiKey;
  if (appState.credentials.geminiModel) headers['X-Gemini-Model'] = appState.credentials.geminiModel;
  if (appState.credentials.geminiBaseUrl) headers['X-Gemini-Base-Url'] = appState.credentials.geminiBaseUrl;
  if (appState.credentials.zoteroKey) headers['X-Zotero-Key'] = appState.credentials.zoteroKey;
  if (appState.credentials.zoteroUserId) headers['X-Zotero-User-Id'] = appState.credentials.zoteroUserId;
  if (appState.credentials.zoteroLibType) headers['X-Zotero-Library-Type'] = appState.credentials.zoteroLibType;
  if (appState.credentials.ncbiKey) headers['X-Ncbi-Key'] = appState.credentials.ncbiKey;
  if (appState.credentials.schoolProxy) headers['X-School-Proxy'] = appState.credentials.schoolProxy;

  options.headers = headers;
  return await fetch(url, options);
}

// Safely parse error messages from responses without crashing on HTML or plain-text 500 errors
async function parseErrorMessage(res) {
  try {
    const data = await res.json();
    return data.detail || data.message || JSON.stringify(data);
  } catch (_) {
    try {
      const text = await res.text();
      return text || `HTTP ${res.status}: ${res.statusText}`;
    } catch (_) {
      return `HTTP ${res.status}: ${res.statusText}`;
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initApp();
});

async function initApp() {
  await checkHealthAndCredentials();
  await loadCollections();
  await loadPapers();
  initDocumentUploadHandlers();
  await loadUploadedDocuments();
}

async function checkHealthAndCredentials() {
  if (!localStorage.getItem('zg_zotero_key') || localStorage.getItem('zg_zotero_key') === 'undefined') {
    localStorage.setItem('zg_zotero_key', DEFAULT_ZOTERO_KEY);
    appState.credentials.zoteroKey = DEFAULT_ZOTERO_KEY;
  }
  if (!localStorage.getItem('zg_zotero_user_id') || localStorage.getItem('zg_zotero_user_id') === 'undefined') {
    localStorage.setItem('zg_zotero_user_id', DEFAULT_ZOTERO_USER_ID);
    appState.credentials.zoteroUserId = DEFAULT_ZOTERO_USER_ID;
  }

  const geminiBadge = document.getElementById('gemini-status');
  const zoteroBadge = document.getElementById('zotero-status');

  try {
    const res = await apiFetch('/api/health');
    const health = await res.json();

    if (health.gemini_configured || appState.credentials.geminiKey) {
      const isMil = (appState.credentials.geminiBaseUrl && appState.credentials.geminiBaseUrl.includes('genai.mil')) || 
                    (appState.credentials.geminiKey && appState.credentials.geminiKey.startsWith('STARK_'));
      const label = isMil ? 'GenAI.mil: Ready' : 'Gemini: Ready';
      geminiBadge.className = 'flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 cursor-pointer';
      geminiBadge.innerHTML = `<i class="fa-solid fa-circle text-[8px] text-emerald-500"></i><span>${label}</span>`;
      geminiBadge.onclick = toggleSettingsModal;
    } else {
      geminiBadge.className = 'flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200 cursor-pointer';
      geminiBadge.innerHTML = `<i class="fa-solid fa-circle text-[8px] text-rose-500"></i><span>Gemini: Missing Key</span>`;
      geminiBadge.onclick = toggleSettingsModal;
    }

    // Check Zotero verification
    const zoteroRes = await apiFetch('/api/zotero/verify');
    const zoteroStatus = await zoteroRes.json();

    if (zoteroStatus.connected) {
      zoteroBadge.className = 'flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200';
      zoteroBadge.innerHTML = `<i class="fa-solid fa-circle text-[8px] text-emerald-500"></i><span>Zotero: Connected</span>`;
    } else {
      zoteroBadge.className = 'flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200 cursor-pointer';
      zoteroBadge.innerHTML = `<i class="fa-solid fa-circle text-[8px] text-rose-500"></i><span>Zotero: Not Connected</span>`;
      zoteroBadge.onclick = toggleSettingsModal;
    }
  } catch (err) {
    console.error('Error verifying services:', err);
  }
}

async function loadCollections() {
  const select = document.getElementById('collection-select');
  try {
    const res = await apiFetch('/api/zotero/collections');
    if (!res.ok) return;
    const collections = await res.json();
    appState.collections = collections;

    select.innerHTML = '<option value="">📁 All Items (Entire Library)</option>';
    collections.forEach(col => {
      const opt = document.createElement('option');
      opt.value = col.key;
      opt.textContent = `📁 ${col.name} (${col.num_items || 0})`;
      select.appendChild(opt);
    });
  } catch (err) {
    console.error('Error loading collections:', err);
  }
}

async function loadPapers(collectionKey = null, query = null) {
  const loading = document.getElementById('paper-loading');
  const list = document.getElementById('paper-list');
  loading.classList.remove('hidden');
  list.innerHTML = '';

  let url = '/api/zotero/items?limit=100';
  if (collectionKey) url += `&collection_key=${encodeURIComponent(collectionKey)}`;
  if (query) url += `&query=${encodeURIComponent(query)}`;

  try {
    const res = await apiFetch(url);
    if (!res.ok) {
      const errMsg = await parseErrorMessage(res);
      loading.innerHTML = `<p class="text-rose-500 font-medium">Failed to load papers: ${escapeHtml(errMsg)}</p>`;
      return;
    }
    const data = await res.json();
    appState.papers = data.items || [];
    renderPaperList();
  } catch (err) {
    loading.innerHTML = `<p class="text-rose-500">Connection error: ${err.message}</p>`;
  } finally {
    loading.classList.add('hidden');
  }
}

function renderPaperList() {
  const list = document.getElementById('paper-list');
  list.innerHTML = '';

  if (appState.papers.length === 0) {
    list.innerHTML = `<div class="text-center py-10 text-slate-400 text-xs">No papers found in this collection.</div>`;
    return;
  }

  appState.papers.forEach(paper => {
    const isSelected = appState.selectedKeys.has(paper.key);
    const isActive = appState.activePaperKey === paper.key;

    const authors = paper.creators && paper.creators.length > 0
      ? (paper.creators.length > 2 ? `${paper.creators[0]} et al.` : paper.creators.join(', '))
      : 'Unknown Author';

    const itemEl = document.createElement('div');
    itemEl.className = `p-3 rounded-lg border transition cursor-pointer flex items-start space-x-3 ${
      isActive ? 'bg-blue-50/70 border-blue-300' : 'bg-white border-slate-200/80 hover:bg-slate-50'
    }`;

    itemEl.innerHTML = `
      <input type="checkbox" data-key="${paper.key}" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation(); togglePaperSelect('${paper.key}')" class="mt-1 rounded text-blue-600 focus:ring-blue-500 h-3.5 w-3.5">
      <div class="flex-1 min-w-0" onclick="setActivePaper('${paper.key}')">
        <h4 class="text-xs font-semibold text-slate-800 leading-snug line-clamp-2">${escapeHtml(paper.title)}</h4>
        <div class="flex items-center space-x-2 mt-1 text-[11px] text-slate-500">
          <span class="truncate max-w-[140px]">${escapeHtml(authors)}</span>
          ${paper.year ? `<span class="bg-slate-100 px-1.5 py-0.2 rounded text-slate-600 font-mono text-[10px]">${paper.year}</span>` : ''}
          ${paper.has_pdf ? `<span class="bg-emerald-100 text-emerald-800 text-[9px] font-bold px-1.5 py-0.2 rounded flex items-center space-x-1"><i class="fa-solid fa-file-pdf"></i><span>PDF</span></span>` : ''}
        </div>
        ${paper.abstract_note ? `<p class="text-[11px] text-slate-400 mt-1 line-clamp-2">${escapeHtml(paper.abstract_note)}</p>` : ''}
      </div>
    `;
    list.appendChild(itemEl);
  });

  updateSelectionDisplay();
}

function setActivePaper(key) {
  appState.activePaperKey = key;
  const paper = appState.papers.find(p => p.key === key);
  if (paper) {
    document.getElementById('single-paper-name').textContent = paper.title;
    document.getElementById('single-paper-name').classList.remove('italic');
  }
  renderPaperList();
}

function togglePaperSelect(key) {
  if (appState.selectedKeys.has(key)) {
    appState.selectedKeys.delete(key);
  } else {
    appState.selectedKeys.add(key);
  }
  updateSelectionDisplay();
}

function toggleSelectAll(selectAll) {
  if (selectAll) {
    appState.papers.forEach(p => appState.selectedKeys.add(p.key));
  } else {
    appState.selectedKeys.clear();
  }
  renderPaperList();
  updateSelectionDisplay();
}

function updateSelectionDisplay() {
  const count = appState.selectedKeys.size;
  document.getElementById('selected-count-badge').textContent = `${count} selected`;
  document.getElementById('synthesis-selection-info').textContent = `${count} selected papers (or all in collection)`;
  document.getElementById('gaps-selection-info').textContent = `${count} selected papers (or all in collection)`;
  document.getElementById('chat-selection-info').textContent = count > 0 ? `${count} selected papers` : 'Entire current collection';
}

function onCollectionChange() {
  const select = document.getElementById('collection-select');
  const collectionKey = select.value || null;
  appState.selectedKeys.clear();
  loadPapers(collectionKey);
}

function debounceSearch() {
  clearTimeout(appState.searchTimeout);
  appState.searchTimeout = setTimeout(() => {
    const query = document.getElementById('paper-search').value.trim();
    const select = document.getElementById('collection-select');
    loadPapers(select.value || null, query || null);
  }, 350);
}

function refreshLibrary() {
  const select = document.getElementById('collection-select');
  loadPapers(select.value || null);
}

function switchTab(tab) {
  appState.activeTab = tab;
  ['deep-dive', 'synthesis', 'gaps', 'chat', 'work-docs', 'literature'].forEach(t => {
    const btn = document.getElementById(`tab-${t}`);
    const panel = document.getElementById(`panel-${t}`);
    if (btn && panel) {
      if (t === tab) {
        btn.className = 'tab-btn px-3 py-1.5 text-xs font-semibold rounded-md bg-blue-600 text-white transition shadow-sm';
        panel.classList.remove('hidden');
      } else {
        btn.className = 'tab-btn px-3 py-1.5 text-xs font-medium rounded-md text-slate-600 hover:bg-slate-100 transition';
        panel.classList.add('hidden');
      }
    }
  });
}

function showLoading(isLoading, message = 'Gemini is analyzing...') {
  const spinner = document.getElementById('loading-spinner');
  if (isLoading) {
    spinner.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin mr-1"></i> ${message}`;
    spinner.classList.remove('hidden');
  } else {
    spinner.classList.add('hidden');
  }
}

function displayReviewOutput(markdownText, zoteroHtml, targetItemKey = null) {
  appState.currentReviewMarkdown = markdownText;
  appState.currentZoteroHtml = zoteroHtml;
  appState.lastAnalyzedItemKey = targetItemKey;

  const placeholder = document.getElementById('output-placeholder');
  const content = document.getElementById('output-content');
  const saveBtn = document.getElementById('save-to-zotero-btn');

  placeholder.classList.add('hidden');
  content.classList.remove('hidden');
  content.innerHTML = marked.parse(markdownText);

  if (targetItemKey) {
    saveBtn.classList.remove('hidden');
  }
}

// -------------------------------------------------------------
// Action Handlers
// -------------------------------------------------------------

async function runSinglePaperReview() {
  if (!appState.activePaperKey) {
    alert('Please click on a paper from the list on the left first!');
    return;
  }

  const focus = document.getElementById('single-focus-input').value.trim();
  const includePdf = document.getElementById('include-pdf-checkbox').checked;

  showLoading(true, 'Gemini is reading and reviewing paper...');
  try {
    const res = await apiFetch('/api/review/paper', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_key: appState.activePaperKey,
        custom_focus: focus || null,
        include_pdf: includePdf
      })
    });

    if (!res.ok) {
      const errMsg = await parseErrorMessage(res);
      throw new Error(errMsg);
    }

    const data = await res.json();
    displayReviewOutput(data.review_markdown, data.zotero_html_note, data.item_key);
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    showLoading(false);
  }
}

async function runCollectionSynthesis() {
  const theme = document.getElementById('synthesis-theme-input').value.trim();
  const select = document.getElementById('collection-select');
  const collectionKey = select.value || null;
  const itemKeys = Array.from(appState.selectedKeys);

  if (itemKeys.length === 0 && !collectionKey) {
    alert('Please select papers with checkboxes or choose a specific collection folder to synthesize.');
    return;
  }

  showLoading(true, 'Gemini is synthesizing literature across papers...');
  try {
    const res = await apiFetch('/api/review/synthesize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_keys: itemKeys.length > 0 ? itemKeys : null,
        collection_key: collectionKey,
        research_theme: theme || null
      })
    });

    if (!res.ok) {
      const errMsg = await parseErrorMessage(res);
      throw new Error(errMsg);
    }

    const data = await res.json();
    displayReviewOutput(data.synthesis_markdown, data.zotero_html_note, itemKeys.length > 0 ? itemKeys[0] : null);
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    showLoading(false);
  }
}

async function runGapAnalysis() {
  const domain = document.getElementById('gaps-domain-input').value.trim();
  const select = document.getElementById('collection-select');
  const collectionKey = select.value || null;
  const itemKeys = Array.from(appState.selectedKeys);

  showLoading(true, 'Gemini is identifying research gaps & proposing study designs...');
  try {
    const res = await apiFetch('/api/review/gaps', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_keys: itemKeys.length > 0 ? itemKeys : null,
        collection_key: collectionKey,
        target_domain: domain || null
      })
    });

    if (!res.ok) {
      const errMsg = await parseErrorMessage(res);
      throw new Error(errMsg);
    }

    const data = await res.json();
    displayReviewOutput(data.markdown, data.zotero_html_note, itemKeys.length > 0 ? itemKeys[0] : null);
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    showLoading(false);
  }
}

async function runChatQuery() {
  const input = document.getElementById('chat-query-input');
  const query = input.value.trim();
  if (!query) return;

  const select = document.getElementById('collection-select');
  const collectionKey = select.value || null;
  const itemKeys = Array.from(appState.selectedKeys);

  showLoading(true, 'Searching library papers & generating answer...');
  try {
    const res = await apiFetch('/api/review/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: query,
        item_keys: itemKeys.length > 0 ? itemKeys : null,
        collection_key: collectionKey,
        chat_history: appState.chatHistory
      })
    });

    if (!res.ok) {
      const errMsg = await parseErrorMessage(res);
      throw new Error(errMsg);
    }

    const data = await res.json();
    appState.chatHistory.push({ role: 'user', content: query });
    appState.chatHistory.push({ role: 'assistant', content: data.answer });

    const chatMd = `### ❓ Question\n> ${query}\n\n### 💡 Answer\n${data.answer}`;
    displayReviewOutput(chatMd, `<p>${data.answer}</p>`);
    input.value = '';
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    showLoading(false);
  }
}

async function saveActiveReviewToZotero() {
  if (!appState.currentReviewMarkdown) {
    alert('No review content available to save.');
    return;
  }

  // 1. If we have an existing Zotero paper key
  const targetKey = appState.lastAnalyzedItemKey || appState.activePaperKey;
  if (targetKey) {
    try {
      const res = await apiFetch(`/api/zotero/items/${targetKey}/save-note`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_key: targetKey,
          note_html: appState.currentZoteroHtml || marked.parse(appState.currentReviewMarkdown),
          tags: ['gemini-reviewed', 'literature-review']
        })
      });

      if (!res.ok) {
        const errMsg = await parseErrorMessage(res);
        throw new Error(errMsg);
      }

      const badge = document.getElementById('doc-sync-badge');
      if (badge) {
        document.getElementById('doc-sync-text').innerText = 'Saved to Zotero';
        badge.classList.remove('hidden');
      }

      alert('✅ Successfully pushed review as a child note to Zotero!');
    } catch (err) {
      alert(`Failed to save note to Zotero: ${err.message}`);
    }
    return;
  }

  // 2. If it is an uploaded work document without an item key yet
  const targetDocId = appState.lastAnalyzedDocumentId || appState.activeDocumentId;
  if (targetDocId) {
    const colSelect = document.getElementById('collection-select');
    const collectionKey = colSelect ? (colSelect.value || null) : null;
    try {
      const res = await apiFetch('/api/documents/save-to-zotero', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          document_id: targetDocId,
          review_markdown: appState.currentReviewMarkdown,
          collection_key: collectionKey
        })
      });

      if (!res.ok) {
        const errMsg = await parseErrorMessage(res);
        throw new Error(errMsg);
      }

      const data = await res.json();
      appState.lastAnalyzedItemKey = data.item_key;
      const badge = document.getElementById('doc-sync-badge');
      if (badge) {
        document.getElementById('doc-sync-text').innerText = 'Saved to Zotero';
        badge.classList.remove('hidden');
      }

      alert('✅ Successfully created document item and attached review note in Zotero!');
    } catch (err) {
      alert(`Failed to save document to Zotero: ${err.message}`);
    }
    return;
  }

  alert('Please select a paper or upload a work document first.');
}

function copyOutputMarkdown() {
  if (!appState.currentReviewMarkdown) {
    alert('No content to copy.');
    return;
  }
  navigator.clipboard.writeText(appState.currentReviewMarkdown);
  alert('Copied review markdown to clipboard!');
}

function downloadOutputMarkdown() {
  if (!appState.currentReviewMarkdown) {
    alert('No review content available to download.');
    return;
  }
  const dateStr = new Date().toISOString().slice(0, 10);
  const blob = new Blob([appState.currentReviewMarkdown], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `GResearch_Analysis_${dateStr}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// -------------------------------------------------------------
// Settings Modal
// -------------------------------------------------------------

function toggleSettingsModal() {
  const modal = document.getElementById('settings-modal');
  modal.classList.toggle('hidden');

  if (!modal.classList.contains('hidden')) {
    const keyInput = document.getElementById('modal-gemini-key');
    const urlInput = document.getElementById('modal-gemini-base-url');
    const modelSelect = document.getElementById('modal-gemini-model');
    const customModelInput = document.getElementById('modal-gemini-model-custom');
    const currentModel = appState.credentials.geminiModel || 'gemini-3.6-flash';

    keyInput.value = appState.credentials.geminiKey || '';
    urlInput.value = appState.credentials.geminiBaseUrl || '';
    document.getElementById('modal-zotero-key').value = appState.credentials.zoteroKey || '';
    document.getElementById('modal-zotero-user-id').value = appState.credentials.zoteroUserId || '';
    document.getElementById('modal-zotero-lib-type').value = appState.credentials.zoteroLibType || 'user';
    document.getElementById('modal-ncbi-key').value = appState.credentials.ncbiKey || '';
    document.getElementById('modal-school-proxy').value = appState.credentials.schoolProxy || '';

    // Match model in dropdown or reveal custom input
    let found = false;
    for (let i = 0; i < modelSelect.options.length; i++) {
      if (modelSelect.options[i].value === currentModel) {
        modelSelect.value = currentModel;
        found = true;
        break;
      }
    }
    if (!found) {
      modelSelect.value = 'custom';
      customModelInput.value = currentModel;
      customModelInput.classList.remove('hidden');
    } else {
      customModelInput.classList.add('hidden');
      customModelInput.value = '';
    }

    modelSelect.onchange = () => {
      if (modelSelect.value === 'custom') {
        customModelInput.classList.remove('hidden');
        customModelInput.focus();
      } else {
        customModelInput.classList.add('hidden');
      }
    };

    // Auto-fill GenAI.mil base URL if user pastes a STARK token
    keyInput.oninput = () => {
      if (keyInput.value.trim().startsWith('STARK_') && !urlInput.value.trim()) {
        urlInput.value = 'https://api.genai.mil/v1';
      }
    };
  }
}

async function saveSettingsFromModal() {
  let gemKey = document.getElementById('modal-gemini-key').value.trim();
  let gemBaseUrl = document.getElementById('modal-gemini-base-url').value.trim();
  if (gemKey.startsWith('STARK_') && !gemBaseUrl) {
    gemBaseUrl = 'https://api.genai.mil/v1';
  }

  const modelSelect = document.getElementById('modal-gemini-model');
  const customModelInput = document.getElementById('modal-gemini-model-custom');
  let chosenModel = modelSelect.value === 'custom' ? customModelInput.value.trim() : modelSelect.value;
  if (!chosenModel) chosenModel = 'gemini-3.6-flash';

  appState.credentials.geminiKey = gemKey;
  appState.credentials.geminiBaseUrl = gemBaseUrl;
  appState.credentials.geminiModel = chosenModel;
  appState.credentials.zoteroKey = document.getElementById('modal-zotero-key').value.trim();
  appState.credentials.zoteroUserId = document.getElementById('modal-zotero-user-id').value.trim();
  appState.credentials.zoteroLibType = document.getElementById('modal-zotero-lib-type').value;
  appState.credentials.ncbiKey = document.getElementById('modal-ncbi-key').value.trim();
  appState.credentials.schoolProxy = document.getElementById('modal-school-proxy').value.trim();

  localStorage.setItem('zg_gemini_key', appState.credentials.geminiKey);
  localStorage.setItem('zg_gemini_base_url', appState.credentials.geminiBaseUrl);
  localStorage.setItem('zg_gemini_model', appState.credentials.geminiModel);
  localStorage.setItem('zg_zotero_key', appState.credentials.zoteroKey);
  localStorage.setItem('zg_zotero_user_id', appState.credentials.zoteroUserId);
  localStorage.setItem('zg_zotero_lib_type', appState.credentials.zoteroLibType);
  localStorage.setItem('zg_ncbi_key', appState.credentials.ncbiKey);
  localStorage.setItem('zg_school_proxy', appState.credentials.schoolProxy);

  toggleSettingsModal();
  await checkHealthAndCredentials();
  await loadCollections();
  await loadPapers();
}

async function fetchAvailableModels() {
  const btn = document.getElementById('btn-refresh-models');
  const modelSelect = document.getElementById('modal-gemini-model');
  const tempKey = document.getElementById('modal-gemini-key').value.trim() || appState.credentials.geminiKey;
  const tempBaseUrl = document.getElementById('modal-gemini-base-url').value.trim() || appState.credentials.geminiBaseUrl;

  if (!tempKey) {
    alert('Please enter your API Key first before refreshing models.');
    return;
  }

  const originalHtml = btn.innerHTML;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Fetching...</span>';
  btn.disabled = true;

  try {
    const headers = { 'X-Gemini-Key': tempKey };
    if (tempBaseUrl) headers['X-Gemini-Base-Url'] = tempBaseUrl;

    const res = await fetch('/api/review/models', { headers });
    if (!res.ok) {
      const err = await parseErrorMessage(res);
      alert(`Could not fetch models: ${err}`);
      return;
    }
    const data = await res.json();
    if (data.models && data.models.length > 0) {
      const currentVal = modelSelect.value === 'custom' 
        ? document.getElementById('modal-gemini-model-custom').value 
        : modelSelect.value;

      modelSelect.innerHTML = '';
      data.models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.display_name && m.display_name !== m.id 
          ? `${m.id} (${m.display_name})` 
          : m.id;
        modelSelect.appendChild(opt);
      });

      // Add Custom Option at end
      const customOpt = document.createElement('option');
      customOpt.value = 'custom';
      customOpt.textContent = '-- Custom Model Name --';
      modelSelect.appendChild(customOpt);

      // Restore previously selected model if still in list
      let matched = false;
      for (let i = 0; i < modelSelect.options.length; i++) {
        if (modelSelect.options[i].value === currentVal) {
          modelSelect.value = currentVal;
          matched = true;
          break;
        }
      }
      if (!matched && currentVal) {
        modelSelect.value = 'custom';
        const customInput = document.getElementById('modal-gemini-model-custom');
        customInput.value = currentVal;
        customInput.classList.remove('hidden');
      }
    }
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    btn.innerHTML = originalHtml;
    btn.disabled = false;
  }
}

function escapeHtml(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// -------------------------------------------------------------
// Work Document Upload & Analysis Handlers
// -------------------------------------------------------------

function initDocumentUploadHandlers() {
  const dropzone = document.getElementById('doc-dropzone');
  if (!dropzone) return;

  ['dragenter', 'dragover'].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.add('border-emerald-600', 'bg-emerald-100/70');
    });
  });

  ['dragleave', 'drop'].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.remove('border-emerald-600', 'bg-emerald-100/70');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleDocumentFileUpload(e.dataTransfer.files);
    }
  });
}

async function handleDocumentFileUpload(files) {
  if (!files || files.length === 0) return;
  const file = files[0];
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    alert('Please upload a PDF file.');
    return;
  }

  showLoading(true, `Uploading and extracting "${file.name}"...`);

  try {
    const formData = new FormData();
    formData.append('file', file);

    const res = await apiFetch('/api/documents/upload', {
      method: 'POST',
      body: formData
    });

    if (!res.ok) {
      const errMsg = await parseErrorMessage(res);
      throw new Error(errMsg);
    }

    const data = await res.json();
    await loadUploadedDocuments();

    // Select this newly uploaded document
    appState.activeDocumentId = data.document_id;
    const select = document.getElementById('active-document-select');
    if (select) select.value = data.document_id;
    onActiveDocumentChange();

    showLoading(false);
  } catch (err) {
    showLoading(false);
    alert(`Upload failed: ${err.message}`);
  }
}

async function loadUploadedDocuments() {
  try {
    const res = await apiFetch('/api/documents/list');
    if (!res.ok) return;
    const docs = await res.json();
    appState.workDocuments = docs;

    const select = document.getElementById('active-document-select');
    const countBadge = document.getElementById('doc-session-count');
    if (!select) return;

    select.innerHTML = '';
    if (docs.length === 0) {
      select.innerHTML = '<option value="">-- No documents uploaded yet --</option>';
      if (countBadge) countBadge.innerText = '0 documents loaded';
      appState.activeDocumentId = null;
      onActiveDocumentChange();
      return;
    }

    if (countBadge) countBadge.innerText = `${docs.length} document${docs.length === 1 ? '' : 's'} loaded`;
    docs.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.id;
      opt.innerText = `${d.title} (${d.page_count} pages)`;
      select.appendChild(opt);
    });

    if (!appState.activeDocumentId || !docs.some(d => d.id === appState.activeDocumentId)) {
      appState.activeDocumentId = docs[0].id;
    }
    select.value = appState.activeDocumentId;
    onActiveDocumentChange();
  } catch (err) {
    console.error('Failed to load documents:', err);
  }
}

function onActiveDocumentChange() {
  const select = document.getElementById('active-document-select');
  const docId = select ? select.value : null;
  appState.activeDocumentId = docId;

  const pagesSpan = document.getElementById('active-doc-pages');
  const sizeSpan = document.getElementById('active-doc-size');
  const deleteBtn = document.getElementById('btn-delete-doc');

  if (!docId) {
    if (pagesSpan) pagesSpan.innerText = 'Pages: -';
    if (sizeSpan) sizeSpan.innerText = 'Size: -';
    if (deleteBtn) deleteBtn.classList.add('hidden');
    return;
  }

  const doc = appState.workDocuments.find(d => d.id === docId);
  if (doc) {
    if (pagesSpan) pagesSpan.innerText = `Pages: ${doc.page_count}`;
    const mb = (doc.file_size_bytes / (1024 * 1024)).toFixed(1);
    if (sizeSpan) sizeSpan.innerText = `Size: ${mb > 0 ? mb : '< 0.1'} MB`;
    if (deleteBtn) deleteBtn.classList.remove('hidden');
  }
}

async function deleteActiveDocument() {
  if (!appState.activeDocumentId) return;
  if (!confirm('Remove this document from the current session?')) return;

  try {
    const res = await apiFetch(`/api/documents/${appState.activeDocumentId}`, {
      method: 'DELETE'
    });
    if (res.ok) {
      await loadUploadedDocuments();
    }
  } catch (err) {
    alert(`Could not remove document: ${err.message}`);
  }
}

async function runWorkDocumentReview() {
  if (!appState.activeDocumentId) {
    alert('Please upload or select a PDF work document first!');
    return;
  }

  const profile = document.getElementById('doc-profile-select').value;
  const customFocus = document.getElementById('doc-custom-focus').value.trim() || null;
  const importToZotero = document.getElementById('doc-auto-zotero').checked;
  const collectionKey = document.getElementById('collection-select').value || null;

  showLoading(true, 'Conducting deep analytical review of work document...');
  const badge = document.getElementById('doc-sync-badge');
  if (badge) badge.classList.add('hidden');

  try {
    const res = await apiFetch('/api/documents/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        document_id: appState.activeDocumentId,
        profile: profile,
        custom_focus: customFocus,
        import_to_zotero: importToZotero,
        collection_key: collectionKey,
        model: appState.credentials.geminiModel || null
      })
    });

    if (!res.ok) {
      const errMsg = await parseErrorMessage(res);
      throw new Error(errMsg);
    }

    const data = await res.json();
    displayReviewOutput(data.review_markdown, null, null);
    appState.lastAnalyzedDocumentId = data.document_id;
    appState.lastAnalyzedItemKey = data.zotero_item_key || null;

    if (data.zotero_saved) {
      if (badge) {
        document.getElementById('doc-sync-text').innerText = 'Saved to Zotero';
        badge.classList.remove('hidden');
      }
    }

    showLoading(false);
  } catch (err) {
    showLoading(false);
    alert(`Document review failed: ${err.message}`);
  }
}

async function runWorkDocChat() {
  if (!appState.activeDocumentId) {
    alert('Please upload or select a document first!');
    return;
  }

  const queryInput = document.getElementById('doc-chat-query');
  const query = queryInput.value.trim();
  if (!query) return;

  showLoading(true, 'Gemini is querying document contents...');
  try {
    const res = await apiFetch('/api/documents/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        document_ids: [appState.activeDocumentId],
        query: query,
        model: appState.credentials.geminiModel || null
      })
    });

    if (!res.ok) {
      const errMsg = await parseErrorMessage(res);
      throw new Error(errMsg);
    }

    const data = await res.json();
    const chatMd = `## 💬 Q&A: ${query}\n\n${data.answer}\n\n---\n*Grounded in: ${data.cited_documents.join(', ') || 'Uploaded Document'}*`;
    
    // Append to review or display in output view
    const current = appState.currentReviewMarkdown ? `${appState.currentReviewMarkdown}\n\n${chatMd}` : chatMd;
    displayReviewOutput(current, null, appState.lastAnalyzedItemKey);
    queryInput.value = '';
    showLoading(false);
  } catch (err) {
    showLoading(false);
    alert(`Chat failed: ${err.message}`);
  }
}

// -------------------------------------------------------------
// Literature Search (PubMed & JSTOR)
// -------------------------------------------------------------

function setLitSource(source) {
  appState.litSource = source;
  const pubmedBtn = document.getElementById('lit-source-pubmed');
  const jstorBtn = document.getElementById('lit-source-jstor');
  const jstorBanner = document.getElementById('jstor-proxy-banner');
  const searchInput = document.getElementById('lit-search-input');

  if (source === 'pubmed') {
    if (pubmedBtn) pubmedBtn.className = 'px-3 py-1.5 text-xs font-semibold rounded bg-white text-blue-700 shadow-xs transition';
    if (jstorBtn) jstorBtn.className = 'px-3 py-1.5 text-xs font-medium rounded text-slate-600 hover:text-slate-900 transition';
    if (jstorBanner) jstorBanner.classList.add('hidden');
    if (searchInput) searchInput.placeholder = "Search PubMed biomedical literature (e.g. 'CRISPR base editing', 'mRNA vaccines')...";
  } else {
    if (jstorBtn) jstorBtn.className = 'px-3 py-1.5 text-xs font-semibold rounded bg-white text-amber-700 shadow-xs transition';
    if (pubmedBtn) pubmedBtn.className = 'px-3 py-1.5 text-xs font-medium rounded text-slate-600 hover:text-slate-900 transition';
    if (jstorBanner) jstorBanner.classList.remove('hidden');
    if (searchInput) searchInput.placeholder = "Search JSTOR humanities & social sciences (e.g. 'deterrence theory', 'contract law')...";
  }
}

async function runLiteratureSearch() {
  const input = document.getElementById('lit-search-input');
  const query = input ? input.value.trim() : '';
  if (!query) {
    alert('Please enter a search topic or keyword.');
    return;
  }

  const limitSelect = document.getElementById('lit-limit-select');
  const limit = limitSelect ? parseInt(limitSelect.value) || 10 : 10;
  const listContainer = document.getElementById('lit-results-list');
  const statusContainer = document.getElementById('lit-results-status');
  const countBadge = document.getElementById('lit-results-count');

  listContainer.innerHTML = `
    <div class="p-8 text-center text-slate-500">
      <i class="fa-solid fa-circle-notch fa-spin text-xl text-indigo-600 mb-2"></i>
      <p class="text-xs">Searching ${appState.litSource === 'pubmed' ? 'NCBI PubMed' : 'JSTOR Academic Repository'}...</p>
    </div>
  `;

  try {
    let endpoint = '/api/external/pubmed/search';
    let body = { query: query, retmax: limit, api_key: appState.credentials.ncbiKey || null };

    if (appState.litSource === 'jstor') {
      endpoint = '/api/external/jstor/search';
      body = { query: query, rows: limit, proxy_prefix: appState.credentials.schoolProxy || null };
    }

    const res = await apiFetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    if (!res.ok) {
      const err = await parseErrorMessage(res);
      throw new Error(err);
    }

    const data = await res.json();
    appState.literatureResults = data.articles || [];

    if (statusContainer) statusContainer.classList.remove('hidden');
    if (countBadge) countBadge.textContent = `Found ${data.total_results.toLocaleString()} articles (showing top ${appState.literatureResults.length})`;

    renderLiteratureResults();
  } catch (err) {
    listContainer.innerHTML = `
      <div class="p-4 bg-rose-50 border border-rose-200 rounded text-rose-700 text-xs">
        <i class="fa-solid fa-triangle-exclamation mr-1"></i> Search failed: ${escapeHtml(err.message)}
      </div>
    `;
  }
}

function renderLiteratureResults() {
  const container = document.getElementById('lit-results-list');
  if (!container) return;

  if (appState.literatureResults.length === 0) {
    container.innerHTML = `
      <div class="p-8 text-center text-slate-400 text-xs bg-slate-50 border border-dashed border-slate-200 rounded-lg">
        <i class="fa-solid fa-magnifying-glass text-2xl mb-2 text-slate-300"></i>
        <p>No articles found matching your query. Try different search terms.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = appState.literatureResults.map((art, idx) => {
    const isPubmed = art.source === 'pubmed';
    const sourceBadge = isPubmed
      ? `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-100 text-blue-800"><i class="fa-solid fa-dna mr-1"></i>PubMed</span>`
      : `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800"><i class="fa-solid fa-book-bookmark mr-1"></i>JSTOR</span>`;

    const authorsStr = art.authors && art.authors.length > 0
      ? escapeHtml(art.authors.slice(0, 3).join(', ') + (art.authors.length > 3 ? ` et al.` : ''))
      : 'Unknown Authors';

    const journalStr = art.journal ? escapeHtml(art.journal) : 'Academic Publication';
    const yearStr = art.publication_year ? ` (${escapeHtml(art.publication_year)})` : '';
    const doiBadge = art.doi ? `<span class="text-[10px] text-slate-500 font-mono">DOI: ${escapeHtml(art.doi)}</span>` : '';
    const pmidBadge = art.pmid ? `<span class="text-[10px] text-slate-500 font-mono">PMID: ${escapeHtml(art.pmid)}</span>` : '';

    const directUrl = art.proxied_url || art.url;
    const accessBtn = directUrl ? `
      <a href="${directUrl}" target="_blank" class="px-2.5 py-1 text-[11px] font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded border border-slate-300 flex items-center space-x-1" title="Open full article with university institutional access">
        <i class="fa-solid fa-graduation-cap text-amber-600"></i>
        <span>${art.source === 'jstor' && appState.credentials.schoolProxy ? 'School Access ↗' : 'Read Paper ↗'}</span>
      </a>
    ` : '';

    const abstractSnippet = art.abstract
      ? `<p class="text-slate-600 text-[11px] mt-1.5 line-clamp-2 leading-relaxed">${escapeHtml(art.abstract)}</p>`
      : `<p class="text-slate-400 italic text-[11px] mt-1.5">Abstract not indexed directly; open paper for full details.</p>`;

    return `
      <div class="p-3 bg-white border border-slate-200 rounded-lg hover:border-indigo-300 hover:shadow-xs transition">
        <div class="flex items-start justify-between gap-2">
          <div class="space-y-0.5 flex-1">
            <div class="flex items-center space-x-2">
              ${sourceBadge}
              <span class="text-[11px] font-medium text-slate-600">${journalStr}${yearStr}</span>
              ${pmidBadge}
              ${doiBadge}
            </div>
            <h4 class="text-xs font-semibold text-slate-900 leading-snug">
              ${escapeHtml(art.title)}
            </h4>
            <div class="text-[11px] text-slate-500">${authorsStr}</div>
          </div>
        </div>

        ${abstractSnippet}

        <div class="flex items-center justify-between mt-2.5 pt-2 border-t border-slate-100">
          <div class="flex items-center space-x-2">
            ${accessBtn}
            <button onclick="reviewExternalArticle(${idx})" class="px-2.5 py-1 text-[11px] font-medium bg-indigo-50 hover:bg-indigo-100 text-indigo-700 rounded border border-indigo-200 flex items-center space-x-1 transition cursor-pointer">
              <i class="fa-solid fa-wand-magic-sparkles text-indigo-600"></i>
              <span>Review with Gemini</span>
            </button>
          </div>

          <button id="btn-import-lit-${idx}" onclick="importExternalArticle(${idx})" class="px-2.5 py-1 text-[11px] font-medium bg-emerald-50 hover:bg-emerald-100 text-emerald-800 rounded border border-emerald-300 flex items-center space-x-1 transition cursor-pointer">
            <i class="fa-solid fa-cloud-arrow-down text-emerald-600"></i>
            <span>Import to Zotero</span>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

async function importExternalArticle(idx) {
  const art = appState.literatureResults[idx];
  if (!art) return;

  const btn = document.getElementById(`btn-import-lit-${idx}`);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Saving...`;
  }

  const select = document.getElementById('collection-select');
  const collectionKey = select ? select.value || null : null;

  try {
    const res = await apiFetch('/api/external/import-to-zotero', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        article: art,
        collection_key: collectionKey
      })
    });

    if (!res.ok) {
      const err = await parseErrorMessage(res);
      throw new Error(err);
    }

    const data = await res.json();
    if (btn) {
      btn.className = 'px-2.5 py-1 text-[11px] font-medium bg-emerald-600 text-white rounded flex items-center space-x-1';
      btn.innerHTML = `<i class="fa-solid fa-check"></i> <span>Saved to Zotero</span>`;
    }
    loadPapers(collectionKey);
  } catch (err) {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-cloud-arrow-down text-emerald-600"></i> Import to Zotero`;
    }
    alert(`Failed to import to Zotero: ${err.message}`);
  }
}

async function reviewExternalArticle(idx) {
  const art = appState.literatureResults[idx];
  if (!art) return;

  if (!appState.credentials.geminiKey) {
    alert('Please set your Gemini / GenAI.mil API Key in Settings first.');
    toggleSettingsModal();
    return;
  }

  showLoading(true, `Gemini is generating an in-depth review of "${art.title.slice(0, 40)}..."`);
  try {
    const res = await apiFetch('/api/external/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        article: art,
        profile: 'technical_critique',
        custom_focus: `Analyze this ${art.source.toUpperCase()} paper rigorously. Synthesize findings, methodology implications, limitations, and future research directions.`,
        import_to_zotero: true,
        collection_key: document.getElementById('collection-select')?.value || null
      })
    });

    if (!res.ok) {
      const errMsg = await parseErrorMessage(res);
      throw new Error(errMsg);
    }

    const data = await res.json();
    displayReviewOutput(data.review_markdown, null, null);
    showLoading(false);
  } catch (err) {
    showLoading(false);
    alert(`Review generation failed: ${err.message}`);
  }
}


