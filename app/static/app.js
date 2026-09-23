let savedModel = localStorage.getItem('zg_gemini_model');
if (savedModel === 'gemini-2.5-flash' || savedModel === 'gemini-3.6-pro') {
  savedModel = 'gemini-3.6-flash';
  localStorage.setItem('zg_gemini_model', savedModel);
}

let appState = {
  activeTab: 'deep-dive',
  collections: [],
  papers: [],
  selectedKeys: new Set(),
  activePaperKey: null,
  currentReviewMarkdown: '',
  currentZoteroHtml: '',
  lastAnalyzedItemKey: null,
  chatHistory: [],
  searchTimeout: null,
  credentials: {
    geminiKey: localStorage.getItem('zg_gemini_key') || '',
    geminiModel: savedModel || 'gemini-3.6-flash',
    geminiBaseUrl: localStorage.getItem('zg_gemini_base_url') || '',
    zoteroKey: localStorage.getItem('zg_zotero_key') || '',
    zoteroUserId: localStorage.getItem('zg_zotero_user_id') || '',
    zoteroLibType: localStorage.getItem('zg_zotero_lib_type') || 'user'
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
}

async function checkHealthAndCredentials() {
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
  ['deep-dive', 'synthesis', 'gaps', 'chat'].forEach(t => {
    const btn = document.getElementById(`tab-${t}`);
    const panel = document.getElementById(`panel-${t}`);
    if (t === tab) {
      btn.className = 'tab-btn px-3 py-1.5 text-xs font-semibold rounded-md bg-blue-600 text-white transition shadow-sm';
      panel.classList.remove('hidden');
    } else {
      btn.className = 'tab-btn px-3 py-1.5 text-xs font-medium rounded-md text-slate-600 hover:bg-slate-100 transition';
      panel.classList.add('hidden');
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
  if (!appState.currentZoteroHtml) {
    alert('No review content available to save.');
    return;
  }

  const targetKey = appState.lastAnalyzedItemKey || appState.activePaperKey;
  if (!targetKey) {
    alert('Please select or specify a paper to attach this review note to in Zotero.');
    return;
  }

  try {
    const res = await apiFetch(`/api/zotero/items/${targetKey}/save-note`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_key: targetKey,
        note_html: appState.currentZoteroHtml,
        tags: ['gemini-reviewed', 'literature-review']
      })
    });

    if (!res.ok) {
      const errMsg = await parseErrorMessage(res);
      throw new Error(errMsg);
    }

    alert('✅ Successfully pushed literature review as a child note to Zotero!');
  } catch (err) {
    alert(`Failed to save to Zotero: ${err.message}`);
  }
}

function copyOutputMarkdown() {
  if (!appState.currentReviewMarkdown) {
    alert('No content to copy.');
    return;
  }
  navigator.clipboard.writeText(appState.currentReviewMarkdown);
  alert('Copied review markdown to clipboard!');
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

  localStorage.setItem('zg_gemini_key', appState.credentials.geminiKey);
  localStorage.setItem('zg_gemini_base_url', appState.credentials.geminiBaseUrl);
  localStorage.setItem('zg_gemini_model', appState.credentials.geminiModel);
  localStorage.setItem('zg_zotero_key', appState.credentials.zoteroKey);
  localStorage.setItem('zg_zotero_user_id', appState.credentials.zoteroUserId);
  localStorage.setItem('zg_zotero_lib_type', appState.credentials.zoteroLibType);

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
