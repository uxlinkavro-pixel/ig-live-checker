document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const accountsInput = document.getElementById('accounts-input');
  const inputLinesCount = document.getElementById('input-lines-count');
  const fileUpload = document.getElementById('file-upload');

  const threadsInput = document.getElementById('threads-input');
  const presetPills = document.querySelectorAll('.preset-pill');
  const delaySlider = document.getElementById('delay-slider');
  const delayVal = document.getElementById('delay-val');
  
  const btnToggleProxy = document.getElementById('btn-toggle-proxy');
  const proxyContent = document.getElementById('proxy-content');
  const proxiesInput = document.getElementById('proxies-input');

  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  const btnClear = document.getElementById('btn-clear');

  const statTotal = document.getElementById('stat-total');
  const statChecked = document.getElementById('stat-checked');
  const statLive = document.getElementById('stat-live');
  const statDead = document.getElementById('stat-dead');
  const statThreads = document.getElementById('stat-threads');
  const statSpeed = document.getElementById('stat-speed');
  const statTime = document.getElementById('stat-time');
  const statProgressSub = document.getElementById('stat-progress-sub');
  const statLiveRate = document.getElementById('stat-live-rate');
  const statDeadRate = document.getElementById('stat-dead-rate');
  const progressBar = document.getElementById('progress-bar');

  const statusIndicator = document.getElementById('status-indicator');
  const statusText = document.getElementById('status-text');

  const liveResultsList = document.getElementById('live-results-list');
  const deadResultsList = document.getElementById('dead-results-list');
  const liveCountBadge = document.getElementById('live-count-badge');
  const deadCountBadge = document.getElementById('dead-count-badge');

  const consoleStream = document.getElementById('console-stream');
  const btnClearLogs = document.getElementById('btn-clear-logs');

  const btnCopyLive = document.getElementById('btn-copy-live');
  const btnDlLive = document.getElementById('btn-dl-live');
  const btnCopyDead = document.getElementById('btn-copy-dead');
  const btnDlDead = document.getElementById('btn-dl-dead');

  // Tracking
  let isChecking = false;
  let pollInterval = null;
  let allLiveAccounts = [];
  let allDeadAccounts = [];
  const MAX_DISPLAY_ITEMS = 120; // Keep UI fast and lag-free

  // Preset Threads Pills
  presetPills.forEach(pill => {
    pill.addEventListener('click', () => {
      presetPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      threadsInput.value = pill.dataset.val;
    });
  });

  threadsInput.addEventListener('input', () => {
    presetPills.forEach(p => {
      if (p.dataset.val === threadsInput.value) {
        p.classList.add('active');
      } else {
        p.classList.remove('active');
      }
    });
  });

  delaySlider.addEventListener('input', (e) => {
    delayVal.textContent = `${e.target.value}s`;
  });

  // Proxy toggle
  btnToggleProxy.addEventListener('click', () => {
    const isHidden = proxyContent.style.display === 'none';
    proxyContent.style.display = isHidden ? 'block' : 'none';
    btnToggleProxy.querySelector('span').textContent = isHidden ? '− Hide Proxies' : '+ Optional Proxies (HTTP / SOCKS5 for high speed)';
  });

  // Input counter
  function updateInputCount() {
    const lines = accountsInput.value.split('\n').filter(l => l.trim().length > 0);
    inputLinesCount.textContent = `${lines.length.toLocaleString()} items`;
  }
  accountsInput.addEventListener('input', updateInputCount);
  updateInputCount();

  // File Upload (.txt / .csv)
  fileUpload.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    showToast(`Loading ${file.name}...`);
    const reader = new FileReader();
    reader.onload = (event) => {
      accountsInput.value = event.target.result;
      updateInputCount();
      showToast(`Loaded ${file.name} successfully!`);
    };
    reader.onerror = () => {
      showToast("Failed to read file.");
    };
    reader.readAsText(file);
    fileUpload.value = ''; // reset
  });

  // Toast Notification
  function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 2200);
  }

  // Polling Server Status
  async function fetchStatus() {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) return;
      const data = await res.json();
      updateUI(data);
    } catch (e) {
      console.warn("Status fetch failed:", e);
    }
  }

  function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(fetchStatus, 350);
  }

  function updateUI(data) {
    isChecking = data.is_running;

    // Button states
    btnStart.disabled = isChecking;
    btnStop.disabled = !isChecking;

    // Header Status Pill
    if (isChecking) {
      statusIndicator.className = 'status-pill running';
      statusText.textContent = `Checking (${data.active_workers} threads)`;
    } else if (data.checked > 0 && data.checked >= data.total) {
      statusIndicator.className = 'status-pill';
      statusText.textContent = 'Completed';
    } else {
      statusIndicator.className = 'status-pill idle';
      statusText.textContent = 'Ready';
    }

    // Counters
    statTotal.textContent = data.total.toLocaleString();
    statChecked.textContent = data.checked.toLocaleString();
    statLive.textContent = data.live_count.toLocaleString();
    statDead.textContent = data.dead_count.toLocaleString();
    statThreads.textContent = data.active_workers;
    statSpeed.textContent = data.error_count > 0 
      ? `${data.speed}/s (${data.error_count} limited)`
      : `${data.speed} / sec`;

    liveCountBadge.textContent = data.live_count.toLocaleString();
    deadCountBadge.textContent = data.dead_count.toLocaleString();

    // Format elapsed time
    const mins = Math.floor(data.elapsed / 60);
    const secs = Math.floor(data.elapsed % 60);
    statTime.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')} elapsed`;

    // Percentage & Progress
    const pct = data.total > 0 ? Math.round((data.checked / data.total) * 100) : 0;
    progressBar.style.width = `${pct}%`;
    statProgressSub.textContent = `${pct}% Processed`;

    const livePct = data.checked > 0 ? Math.round((data.live_count / data.checked) * 100) : 0;
    const deadPct = data.checked > 0 ? Math.round((data.dead_count / data.checked) * 100) : 0;
    statLiveRate.textContent = `${livePct}% Live`;
    statDeadRate.textContent = `${deadPct}% Dead`;

    // High performance rendering: render recent items
    const liveRecent = data.live_list_recent || [];
    if (liveRecent.length > 0) {
      const itemsToRender = liveRecent.slice(-MAX_DISPLAY_ITEMS).reverse();
      liveResultsList.innerHTML = itemsToRender.map(item => `
        <div class="result-item">
          <div class="item-left">
            <a href="https://instagram.com/${item.username}" target="_blank" class="item-user">@${item.username}</a>
            ${item.name ? `<span class="item-name">${item.name}</span>` : ''}
          </div>
          <span class="tag-badge tag-green">LIVE</span>
        </div>
      `).join('');
    }

    const deadRecent = data.dead_list_recent || [];
    if (deadRecent.length > 0) {
      const itemsToRender = deadRecent.slice(-MAX_DISPLAY_ITEMS).reverse();
      deadResultsList.innerHTML = itemsToRender.map(item => `
        <div class="result-item">
          <div class="item-left">
            <span class="item-user">@${item.username}</span>
            <span class="item-meta">${item.reason || 'Dead'}</span>
          </div>
          <span class="tag-badge tag-red">DEAD</span>
        </div>
      `).join('');
    }

    // Update Logs
    if (data.logs && data.logs.length > 0) {
      const logsHtml = data.logs.map(l => {
        let cls = 'log-line text-dim';
        let badge = `[${l.status}]`;
        if (l.status === 'LIVE') cls = 'log-line log-live';
        else if (l.status === 'DEAD') cls = 'log-line log-dead';
        else if (l.status === 'LIMITED') cls = 'log-line log-limited';

        return `<div class="${cls}"><span class="log-time">[${l.time}]</span> ${badge} @${l.username} ${l.detail ? `— ${l.detail}` : ''}</div>`;
      }).join('');
      consoleStream.innerHTML = logsHtml;
      consoleStream.scrollTop = consoleStream.scrollHeight;
    }

    // Adjust polling speed if finished
    if (!isChecking && data.checked >= data.total && pollInterval) {
      clearInterval(pollInterval);
      pollInterval = setInterval(fetchStatus, 1500);
    }
  }

  // Start Checking
  btnStart.addEventListener('click', async () => {
    const raw = accountsInput.value.trim();
    if (!raw) {
      showToast("Please enter accounts or upload a file!");
      accountsInput.focus();
      return;
    }

    liveResultsList.innerHTML = '<div class="empty-state">Checking live accounts...</div>';
    deadResultsList.innerHTML = '<div class="empty-state">Checking dead accounts...</div>';

    const threads = parseInt(threadsInput.value) || 50;
    const delay = parseFloat(delaySlider.value);

    try {
      const res = await fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          accounts: raw,
          threads: threads,
          delay: delay,
          proxies: proxiesInput.value.trim()
        })
      });

      const resData = await res.json();
      if (res.ok) {
        showToast(`Started checking ${resData.total.toLocaleString()} accounts with ${resData.threads} threads!`);
        startPolling();
      } else {
        showToast(`Error: ${resData.error || 'Failed to start'}`);
      }
    } catch (e) {
      showToast("Server connection error!");
    }
  });

  // Stop Checking
  btnStop.addEventListener('click', async () => {
    try {
      await fetch('/api/stop', { method: 'POST' });
      showToast("Stopping process...");
    } catch (e) {
      showToast("Failed to stop.");
    }
  });

  // Clear All
  btnClear.addEventListener('click', async () => {
    if (confirm("Clear all accounts and results?")) {
      await fetch('/api/clear', { method: 'POST' });
      accountsInput.value = '';
      proxiesInput.value = '';
      updateInputCount();
      liveResultsList.innerHTML = '<div class="empty-state">No live accounts detected yet.</div>';
      deadResultsList.innerHTML = '<div class="empty-state">No dead accounts detected yet.</div>';
      consoleStream.innerHTML = '<div class="log-line text-dim"><span class="log-time">[System]</span> Cleared all data.</div>';
      fetchStatus();
      showToast("Cleared all data.");
    }
  });

  // Clear Logs
  btnClearLogs.addEventListener('click', () => {
    consoleStream.innerHTML = '<div class="log-line text-dim"><span class="log-time">[System]</span> Log view cleared.</div>';
  });

  // Download directly from backend stream (guarantees 100% full export even with 500k accounts)
  btnDlLive.addEventListener('click', () => {
    window.location.href = '/api/export/live';
    showToast("Downloading all Live accounts...");
  });

  btnDlDead.addEventListener('click', () => {
    window.location.href = '/api/export/dead';
    showToast("Downloading all Dead accounts...");
  });

  // Copy Live
  btnCopyLive.addEventListener('click', async () => {
    showToast("Preparing live accounts...");
    try {
      const res = await fetch('/api/export/live');
      const text = await res.text();
      if (!text.trim()) {
        showToast("Live list is empty!");
        return;
      }
      await navigator.clipboard.writeText(text);
      const count = text.split('\n').filter(l => l.trim()).length;
      showToast(`Copied ${count.toLocaleString()} Live accounts to clipboard!`);
    } catch (e) {
      showToast("Failed to copy.");
    }
  });

  // Copy Dead
  btnCopyDead.addEventListener('click', async () => {
    showToast("Preparing dead accounts...");
    try {
      const res = await fetch('/api/export/dead');
      const text = await res.text();
      if (!text.trim()) {
        showToast("Dead list is empty!");
        return;
      }
      await navigator.clipboard.writeText(text);
      const count = text.split('\n').filter(l => l.trim()).length;
      showToast(`Copied ${count.toLocaleString()} Dead accounts to clipboard!`);
    } catch (e) {
      showToast("Failed to copy.");
    }
  });

  // Initial check
  fetchStatus();
});
