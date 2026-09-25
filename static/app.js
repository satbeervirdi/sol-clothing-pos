/**
 * SOL • SOUL OF LIFESTYLE - POS & CRM Application Logic
 * Pure Monochrome Black & White Luxury Operating System
 * Interconnects Inventory, Real-Time Billing, Customer CRM, Google Sheets, Gmail, WhatsApp & Mobile.
 */

// Global State
let state = {
  cart: [],
  selectedCustomer: null,
  allCustomers: [],
  allProducts: [],
  categories: [],
  settings: {
    store_name: 'SOL • Soul of Lifestyle',
    tagline: 'PREMIUM WEAR | MODERN ESSENTIALS | ELEVATED YOU',
    phone: '+91 98765 43210',
    email: 'contact@solwear.com',
    address: 'Flagship Store, Fashion Avenue, MG Road',
    gstin: '29AAAAA1234A1Z1',
    currency_symbol: '₹',
    default_tax_rate: 5.0,
    upi_id: 'sol@upi',
    return_policy: 'Exchange within 7 days with original tags and bill intact. No cash refunds.',
    google_sheets_webhook_url: '',
    gmail_sender: '',
    gmail_app_password: ''
  },
  discountType: 'fixed',
  discountVal: 0,
  taxRate: 5.0,
  paymentMethod: 'Cash',
  cashTendered: 0,
  lastCompletedInvoice: null,
  activeCategory: 'All',
  scannerInstance: null,
  isScannerRunning: false,
  barcodeBuffer: '',
  lastBarcodeTime: 0
};

// ==============================================================
// 1. INITIALIZATION & PWA SERVICE WORKER
// ==============================================================

document.addEventListener('DOMContentLoaded', async () => {
  registerPWA();
  setupGlobalBarcodeListener();
  await loadSettings();
  await loadCategories();
  await loadProducts();
  await loadCustomers();
  await loadSoldProductsModal();
  renderPosCategoryChips();
  calculateBillTotals();
  populateMobileIp();
  const scanInput = document.getElementById('barcode-scan-input');
  if (scanInput) setTimeout(() => scanInput.focus(), 150);
});

function registerPWA() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js').catch(err => {
      console.log('SW registration note:', err);
    });
  }
}

function populateMobileIp() {
  const display = document.getElementById('mobile-local-ip-display');
  if (display) {
    const host = window.location.hostname;
    const port = window.location.port || '8000';
    if (host === 'localhost' || host === '127.0.0.1') {
      display.textContent = `http://192.168.1.167:${port}`;
    } else {
      display.textContent = `http://${host}:${port}`;
    }
  }
}

// Audio Feedback using Web Audio API (Zero-latency instant beep)
function playBeep(freq = 880, duration = 0.08, type = 'sine') {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration);
  } catch (e) {}
}

function playSuccessChime() {
  playBeep(523.25, 0.08);
  setTimeout(() => playBeep(659.25, 0.08), 80);
  setTimeout(() => playBeep(783.99, 0.15), 160);
}

// ==============================================================
// 2. TAB NAVIGATION
// ==============================================================

function switchTab(tabId) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.remove('active', 'bg-white', 'text-black');
    btn.classList.add('text-zinc-400');
  });

  const activeSection = document.getElementById(`tab-${tabId}`);
  const activeBtn = document.getElementById(`tab-btn-${tabId}`);
  if (activeSection) activeSection.classList.remove('hidden');
  if (activeBtn) {
    activeBtn.classList.add('active', 'bg-white', 'text-black');
    activeBtn.classList.remove('text-zinc-400');
  }

  // Toggle mobile sticky checkout bar: only show on billing/pos tab if cart has items
  const mobileSticky = document.getElementById('mobile-sticky-checkout');
  if (mobileSticky) {
    if ((tabId === 'pos' || tabId === 'billing') && state.cart && state.cart.length > 0) {
      mobileSticky.classList.remove('hidden');
    } else {
      mobileSticky.classList.add('hidden');
    }
  }

  if (tabId === 'pos' || tabId === 'billing') {
    const scanInput = document.getElementById('barcode-scan-input');
    if (scanInput) setTimeout(() => scanInput.focus(), 50);
  }
  if (tabId === 'inventory') loadInventory();
  if (tabId === 'crm') loadCRM();
  if (tabId === 'analytics') loadAnalytics();
  if (tabId === 'tags') {
    initTagStudio();
    renderGarmentTags();
  }
  if (tabId === 'integrations') populateIntegrationsUI();
}

// ==============================================================
// 3. SETTINGS & BRAND CONFIGURATION
// ==============================================================

async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    if (res.ok) {
      state.settings = await res.json();
      applySettingsToUI();
    }
  } catch (err) {
    console.error('Failed to load settings:', err);
  }
}

function applySettingsToUI() {
  const s = state.settings;

  // Currency symbols across UI
  document.querySelectorAll('.currency-symbol').forEach(el => {
    el.textContent = s.currency_symbol || '₹';
  });

  // Settings tab fields
  document.getElementById('set-store-name').value = s.store_name || 'SOL • Soul of Lifestyle';
  document.getElementById('set-tagline').value = s.tagline || 'PREMIUM WEAR | MODERN ESSENTIALS | ELEVATED YOU';
  document.getElementById('set-phone').value = s.phone || '';
  document.getElementById('set-email').value = s.email || '';
  document.getElementById('set-address').value = s.address || '';
  document.getElementById('set-gstin').value = s.gstin || '';
  document.getElementById('set-currency').value = s.currency_symbol || '₹';
  document.getElementById('set-tax').value = s.default_tax_rate || 5.0;
  document.getElementById('set-upi').value = s.upi_id || '';
  document.getElementById('set-policy').value = s.return_policy || '';

  const upiDisplay = document.getElementById('upi-display-id');
  if (upiDisplay) upiDisplay.textContent = s.upi_id || 'sol@upi';

  state.taxRate = s.default_tax_rate || 5.0;
  const taxSelect = document.getElementById('tax-rate-select');
  if (taxSelect) taxSelect.value = state.taxRate;

  populateIntegrationsUI();
}

function populateIntegrationsUI() {
  const s = state.settings;
  const sheetsInput = document.getElementById('int-sheets-url');
  if (sheetsInput) sheetsInput.value = s.google_sheets_webhook_url || '';

  const gmailUser = document.getElementById('int-gmail-user');
  if (gmailUser) gmailUser.value = s.gmail_sender || '';

  const gmailPass = document.getElementById('int-gmail-password');
  if (gmailPass) gmailPass.value = s.gmail_app_password || '';
}

async function saveStoreSettings() {
  const payload = {
    store_name: document.getElementById('set-store-name').value.trim() || 'SOL • Soul of Lifestyle',
    tagline: document.getElementById('set-tagline').value.trim() || 'PREMIUM WEAR | MODERN ESSENTIALS | ELEVATED YOU',
    phone: document.getElementById('set-phone').value.trim(),
    email: document.getElementById('set-email').value.trim(),
    address: document.getElementById('set-address').value.trim(),
    gstin: document.getElementById('set-gstin').value.trim(),
    currency_symbol: document.getElementById('set-currency').value.trim() || '₹',
    default_tax_rate: parseFloat(document.getElementById('set-tax').value) || 0,
    upi_id: document.getElementById('set-upi').value.trim(),
    return_policy: document.getElementById('set-policy').value.trim(),
    google_sheets_webhook_url: state.settings.google_sheets_webhook_url || '',
    gmail_sender: state.settings.gmail_sender || '',
    gmail_app_password: state.settings.gmail_app_password || ''
  };

  try {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      state.settings = await res.json();
      applySettingsToUI();
      alert('SOL Brand Settings saved successfully!');
    }
  } catch (err) {
    alert('Error saving settings: ' + err.message);
  }
}

async function saveWebhookFromIntegrations() {
  const url = document.getElementById('int-sheets-url').value.trim();
  state.settings.google_sheets_webhook_url = url;
  
  const payload = {
    ...state.settings,
    google_sheets_webhook_url: url
  };

  try {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      alert('Google Sheets Webhook URL saved successfully!');
    }
  } catch (e) {
    alert('Error saving webhook: ' + e.message);
  }
}

async function saveGmailFromIntegrations() {
  const user = document.getElementById('int-gmail-user').value.trim();
  const pass = document.getElementById('int-gmail-password').value.trim();
  
  const payload = {
    ...state.settings,
    gmail_sender: user,
    gmail_app_password: pass
  };

  try {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      state.settings.gmail_sender = user;
      state.settings.gmail_app_password = pass;
      alert('Gmail settings saved successfully!');
    }
  } catch (e) {
    alert('Error saving Gmail settings: ' + e.message);
  }
}

function copyAppsScriptCode() {
  const code = document.getElementById('apps-script-snippet').innerText;
  navigator.clipboard.writeText(code).then(() => {
    const btn = document.getElementById('copy-script-btn');
    btn.innerHTML = `<i class="fa-solid fa-check mr-1"></i> Copied!`;
    setTimeout(() => {
      btn.innerHTML = `<i class="fa-solid fa-copy mr-1"></i> Copy Script`;
    }, 2000);
  });
}

// 1-Click CSV Export for Google Sheets
function downloadCSV(entity) {
  window.open(`/api/export/csv/${entity}`, '_blank');
}

// Bulk Import from Google Sheets CSV
async function handleCSVImportUpload() {
  const fileInput = document.getElementById('csv-import-file');
  if (!fileInput.files || fileInput.files.length === 0) {
    alert('Please select a .csv file exported from your Google Sheet or Excel.');
    return;
  }

  const file = fileInput.files[0];
  const reader = new FileReader();

  reader.onload = async (e) => {
    const csvContent = e.target.result;
    try {
      const res = await fetch('/api/import/csv/products', {
        method: 'POST',
        headers: { 'Content-Type': 'text/csv' },
        body: csvContent
      });
      if (res.ok) {
        const data = await res.json();
        alert(`Successfully imported styles! Created: ${data.created}, Updated: ${data.updated}`);
        await loadProducts();
        await loadCategories();
        renderPosCategoryChips();
        loadInventory();
        fileInput.value = '';
      } else {
        alert('Failed to parse CSV.');
      }
    } catch (err) {
      alert('Import error: ' + err.message);
    }
  };

  reader.readAsText(file);
}

// ==============================================================
// 4. SCANNER & HARDWARE BARCODE LISTENER
// ==============================================================

function setupGlobalBarcodeListener() {
  window.addEventListener('keydown', (e) => {
    const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
    if (activeTag === 'textarea' || (activeTag === 'input' && document.activeElement.id !== 'barcode-scan-input')) {
      return;
    }

    const currentTime = new Date().getTime();

    if (e.key === 'Enter') {
      if (state.barcodeBuffer.length > 2) {
        processScannedCode(state.barcodeBuffer.trim());
        state.barcodeBuffer = '';
        e.preventDefault();
      }
    } else if (e.key.length === 1) {
      if (currentTime - state.lastBarcodeTime > 150) {
        state.barcodeBuffer = '';
      }
      state.barcodeBuffer += e.key;
      state.lastBarcodeTime = currentTime;
    }
  });
}

function handleBarcodeKeydown(e) {
  if (e.key === 'Enter') {
    const code = e.target.value.trim();
    if (code) {
      processScannedCode(code);
      e.target.value = '';
    }
  }
}

let isCameraScanningActive = false;

function showScanToast(msg, isError = false) {
  let toast = document.getElementById('scan-toast-alert');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'scan-toast-alert';
    document.body.appendChild(toast);
  }
  toast.className = isError
    ? 'fixed top-5 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-2xl text-xs font-bold shadow-2xl flex items-center gap-2 transition-all duration-300 pointer-events-none bg-red-950 border border-red-800 text-red-200'
    : 'fixed top-5 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-2xl text-xs font-bold shadow-2xl flex items-center gap-2 transition-all duration-300 pointer-events-none bg-zinc-900 border border-zinc-700 text-white';
  toast.innerHTML = isError
    ? `<i class="fa-solid fa-circle-exclamation text-red-400"></i><span>${escapeHtml(msg)}</span>`
    : `<i class="fa-solid fa-circle-check text-emerald-400"></i><span>${escapeHtml(msg)}</span>`;
  toast.style.opacity = '1';
  toast.style.transform = 'translate(-50%, 0)';
  
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translate(-50%, -10px)';
  }, 2400);
}

async function processScannedCode(code) {
  if (!code) return;
  try {
    const res = await fetch(`/api/products/lookup/${encodeURIComponent(code)}`);
    if (res.ok) {
      const prod = await res.json();
      playBeep(987.77, 0.12);
      addProductToCart(prod);
      const name = prod.product_name || prod.name;
      const variant = [prod.size, prod.color].filter(Boolean).join(' / ');
      showScannerStatus(`Added: ${name} (${variant || '-'}) - ${state.settings.currency_symbol || '₹'}${prod.selling_price}`);
      showScanToast(`Added: ${name} (${variant || '-'}) - ${state.settings.currency_symbol || '₹'}${prod.selling_price}`);
    } else {
      playBeep(250, 0.2, 'sawtooth');
      showScannerStatus(`Style with code '${code}' not found in SOL inventory`, true);
      showScanToast(`Style '${code}' not found in inventory`, true);
    }
  } catch (err) {
    showScannerStatus(`Scan error: ${err.message}`, true);
    showScanToast(`Scan error: ${err.message}`, true);
  }
}

function showScannerStatus(msg, isError = false) {
  const el = document.getElementById('scanner-last-detected');
  if (el) {
    el.textContent = msg;
    el.className = isError ? 'mt-3 text-center text-xs text-zinc-400 font-mono truncate' : 'mt-3 text-center text-xs text-white font-mono truncate';
  }
}

function openLiveScannerModal() {
  const modal = document.getElementById('modal-scanner');
  if (!modal) return;
  modal.classList.remove('hidden');
  showScannerStatus('Activating camera...');
  isCameraScanningActive = true;

  setTimeout(() => {
    try {
      if (!state.scannerInstance) {
        state.scannerInstance = new Html5Qrcode("qr-reader");
      }
      
      const config = { 
        fps: 10, 
        qrbox: { width: 220, height: 220 },
        aspectRatio: 1.0
      };

      state.scannerInstance.start(
        { facingMode: "environment" },
        config,
        async (decodedText) => {
          // Prevent multiple frames from triggering bulk additions!
          if (!isCameraScanningActive) return;
          isCameraScanningActive = false; // Immediately lock on the FIRST detected frame

          // Close camera immediately so cashier is not stuck on the camera view
          await closeLiveScannerModal();

          // Beep & process product
          await processScannedCode(decodedText.trim());
        },
        () => {}
      ).then(() => {
        state.isScannerRunning = true;
        showScannerStatus('Camera active. Point at SOL Garment QR or Barcode.');
      }).catch(err => {
        isCameraScanningActive = false;
        showScannerStatus('Camera access error: ' + err, true);
      });
    } catch (e) {
      isCameraScanningActive = false;
      showScannerStatus('Scanner initialization failed: ' + e.message, true);
    }
  }, 150);
}

async function closeLiveScannerModal() {
  isCameraScanningActive = false;
  const modal = document.getElementById('modal-scanner');
  if (modal) modal.classList.add('hidden');
  
  if (state.scannerInstance && state.isScannerRunning) {
    try {
      await state.scannerInstance.stop();
      state.isScannerRunning = false;
    } catch (e) {
      console.warn('Scanner stop note:', e);
    }
  }
}

// ==============================================================
// 5. BILLING CART & DYNAMIC ON-THE-FLY OVERRIDES
// ==============================================================

function addProductToCart(prod) {
  // If success view is visible from previous bill, dismiss and show cart
  hideSuccessViewAndShowCart();
  
  const vId = prod.variant_id || null;
  const pId = prod.product_id || prod.id;
  const sku = prod.sku;
  
  // Find exact variant in cart
  const existing = state.cart.find(it => 
    (vId && it.variant_id === vId) || 
    (sku && it.sku === sku) || 
    (pId && it.product_id === pId && it.size === prod.size && it.color === prod.color)
  );
  
  const maxStock = prod.available_stock !== undefined ? prod.available_stock : (prod.stock_quantity !== undefined ? prod.stock_quantity : 999);
  
  if (existing) {
    if (existing.quantity + 1 > existing.current_stock) {
      playBeep(250, 0.2, 'sawtooth');
      showScannerStatus(`Cannot add more: Only ${existing.current_stock} units available for ${prod.product_name || prod.name}`, true);
      alert(`Only ${existing.current_stock} units available.`);
      return;
    }
    existing.quantity += 1;
    existing.line_total = Math.max(0, (existing.unit_price * existing.quantity) - existing.discount_amount);
  } else {
    if (maxStock <= 0) {
      playBeep(250, 0.2, 'sawtooth');
      showScannerStatus(`Cannot add: '${prod.product_name || prod.name}' is Out of Stock!`, true);
      alert(`Cannot add: '${prod.product_name || prod.name}' is Out of Stock!`);
      return;
    }
    state.cart.push({
      product_id: pId,
      variant_id: vId,
      sku: prod.sku,
      barcode: prod.barcode || prod.sku,
      product_name: prod.product_name || prod.name,
      image_url: prod.image || prod.image_url || null,
      size: prod.size || 'Free Size',
      color: prod.color || 'Standard',
      category: prod.category || 'General',
      gst_rate: prod.gst_rate || 5.0,
      unit_price: prod.selling_price,
      quantity: 1,
      discount_amount: 0.0,
      line_total: prod.selling_price,
      current_stock: maxStock
    });
  }
  renderCart();
  calculateBillTotals();
  
  // Keep keyboard focus on barcode input for continuous rapid cashier scanning: SCAN -> BEEP -> ADD
  const input = document.getElementById('barcode-scan-input');
  if (input) input.focus();
}

function openCustomItemModal() {
  document.getElementById('custom-item-name').value = '';
  document.getElementById('custom-item-price').value = '';
  document.getElementById('custom-item-qty').value = '1';
  document.getElementById('custom-item-size').value = '';
  document.getElementById('custom-item-color').value = '';
  document.getElementById('modal-custom-item').classList.remove('hidden');
  setTimeout(() => document.getElementById('custom-item-name').focus(), 100);
}

function closeCustomItemModal() {
  document.getElementById('modal-custom-item').classList.add('hidden');
}

function addCustomItemToCart() {
  const name = document.getElementById('custom-item-name').value.trim();
  const price = parseFloat(document.getElementById('custom-item-price').value);
  const qty = parseInt(document.getElementById('custom-item-qty').value) || 1;
  const size = document.getElementById('custom-item-size').value.trim();
  const color = document.getElementById('custom-item-color').value.trim();

  if (!name) {
    alert('Please enter an item or service name.');
    return;
  }
  if (isNaN(price) || price < 0) {
    alert('Please enter a valid price.');
    return;
  }

  hideSuccessViewAndShowCart();

  state.cart.push({
    product_id: null,
    variant_id: null,
    sku: 'CUSTOM',
    product_name: name,
    image_url: null,
    size: size || 'Custom',
    color: color || '-',
    unit_price: price,
    quantity: qty,
    discount_amount: 0.0,
    line_total: price * qty,
    current_stock: 999
  });

  playBeep(700, 0.08);
  closeCustomItemModal();
  renderCart();
  calculateBillTotals();
}

function renderCart() {
  const tbody = document.getElementById('cart-items-body');
  const mobileContainer = document.getElementById('cart-items-mobile');
  const emptyPlaceholder = document.getElementById('cart-empty-placeholder');
  const tableView = document.getElementById('cart-table-view');
  const badge = document.getElementById('cart-item-count-badge');
  const stockAlert = document.getElementById('cart-stock-alert');
  const stockAlertMsg = document.getElementById('cart-stock-alert-msg');
  const checkoutBtn = document.getElementById('checkout-btn');
  const mobileCheckoutBtn = document.getElementById('mobile-checkout-btn');
  const mobileSticky = document.getElementById('mobile-sticky-checkout');
  
  const totalUnits = state.cart.reduce((sum, item) => sum + item.quantity, 0);
  if (badge) badge.textContent = `${totalUnits} ${totalUnits === 1 ? 'item' : 'items'}`;

  if (state.cart.length === 0) {
    if (tbody) tbody.innerHTML = '';
    if (mobileContainer) mobileContainer.innerHTML = '';
    if (tableView) tableView.classList.add('hidden');
    if (emptyPlaceholder) emptyPlaceholder.classList.remove('hidden');
    if (stockAlert) stockAlert.classList.add('hidden');
    if (mobileSticky) mobileSticky.classList.add('hidden');
    if (checkoutBtn) {
      checkoutBtn.disabled = false;
      checkoutBtn.className = "w-full py-3.5 px-4 rounded-xl bg-white hover:bg-zinc-200 text-black font-extrabold text-sm shadow-xl flex items-center justify-center gap-2 transition active:scale-[0.99]";
      checkoutBtn.innerHTML = `<i class="fa-solid fa-bolt-lightning text-xs"></i><span>COMPLETE SALE & GENERATE BILL</span>`;
    }
    if (mobileCheckoutBtn) {
      mobileCheckoutBtn.disabled = false;
      mobileCheckoutBtn.className = "flex-1 max-w-[210px] py-2.5 px-4 rounded-xl bg-white hover:bg-zinc-200 text-black font-extrabold text-xs uppercase tracking-wider flex items-center justify-center gap-1.5 shadow-lg active:scale-95 transition";
      mobileCheckoutBtn.innerHTML = `<i class="fa-solid fa-bolt-lightning text-xs"></i><span>Complete Sale</span>`;
    }
    return;
  }

  if (emptyPlaceholder) emptyPlaceholder.classList.add('hidden');
  if (tableView) tableView.classList.remove('hidden');
  if (mobileSticky) mobileSticky.classList.remove('hidden');
  if (tbody) tbody.innerHTML = '';
  if (mobileContainer) mobileContainer.innerHTML = '';

  let hasStockShortage = false;
  let shortageItemName = '';
  let shortageAvailable = 0;

  state.cart.forEach((item, index) => {
    const isShortage = (item.current_stock !== undefined && item.quantity > item.current_stock);
    
    if (isShortage) {
      hasStockShortage = true;
      shortageItemName = item.product_name;
      shortageAvailable = item.current_stock;
    }

    const stockBadge = (item.current_stock !== undefined && item.current_stock < 900)
      ? (isShortage
          ? `<span class="text-[9px] text-red-400 font-bold ml-1.5 bg-red-950 px-1.5 py-0.5 rounded border border-red-800">Only ${item.current_stock} available!</span>`
          : `<span class="text-[9px] text-zinc-500 font-bold ml-1.5">[Stock: ${item.current_stock}]</span>`)
      : '';

    // 1. Desktop Row (Hidden on mobile < 640px)
    if (tbody) {
      const tr = document.createElement('tr');
      tr.className = isShortage ? 'luxury-row text-xs border-b border-red-900/60 bg-red-950/20' : 'luxury-row text-xs border-b border-zinc-850';
      tr.innerHTML = `
        <td class="py-2.5 px-3">
          <div class="flex items-center gap-2.5">
            ${item.image_url ? `
              <img src="${item.image_url}" alt="${escapeHtml(item.product_name)}" 
                class="w-9 h-9 object-cover rounded-lg border border-zinc-800 flex-shrink-0 cursor-pointer hover:opacity-80 transition shadow-sm" 
                title="Click to preview photo"
                onclick="openImagePreviewModal('${item.image_url}', '${escapeHtml(item.product_name)}')">
            ` : `
              <div class="w-9 h-9 rounded-lg bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-600 flex-shrink-0">
                <i class="fa-solid fa-shirt text-xs"></i>
              </div>
            `}
            <div class="flex-1 min-w-0">
              <!-- Editable Product Name -->
              <input type="text" value="${escapeHtml(item.product_name)}" 
                class="bg-transparent border-b border-dashed border-zinc-800 hover:border-white focus:border-white focus:bg-black rounded px-1 py-0.5 text-white font-bold w-full text-xs focus:outline-none transition" 
                title="Click to rename" onchange="updateCartItemName(${index}, this.value)">
              <div class="flex items-center gap-1.5 mt-0.5 text-[10px] text-zinc-400 font-mono flex-wrap">
                <span class="px-1.5 py-0.2 rounded bg-zinc-900 text-zinc-300 font-bold">${item.sku || 'CUSTOM'}</span>
                ${item.size ? `<span class="bg-zinc-900 px-1.5 py-0.2 rounded text-white font-bold">${item.size}</span>` : ''}
                ${item.color ? `<span>${item.color}</span>` : ''}
                ${stockBadge}
              </div>
            </div>
          </div>
        </td>
        <td class="py-2.5 px-2 text-center">
          <div class="flex items-center justify-center">
            <span class="text-zinc-500 font-mono text-xs mr-0.5">${state.settings.currency_symbol || '₹'}</span>
            <input type="number" min="0" step="any" value="${item.unit_price}" 
              class="w-20 bg-pitch border border-zinc-800 rounded px-1.5 py-1 text-center font-mono font-bold text-emerald-400 focus:outline-none focus:border-emerald-400 text-xs"
              title="Click to change price" onchange="updateCartItemPrice(${index}, this.value)">
          </div>
        </td>
        <td class="py-2.5 px-2 text-center">
          <div class="inline-flex items-center rounded-lg bg-pitch border ${isShortage ? 'border-red-600 bg-red-950/40' : 'border-zinc-800'} p-0.5">
            <button onclick="updateCartItemQty(${index}, -1)" class="w-6 h-6 rounded flex items-center justify-center text-zinc-400 hover:text-white hover:bg-zinc-800 transition font-bold text-xs">-</button>
            <input type="number" min="1" value="${item.quantity}" 
              class="w-9 bg-transparent text-center font-mono font-bold ${isShortage ? 'text-red-400' : 'text-white'} text-xs focus:outline-none"
              onchange="setCartItemQty(${index}, this.value)">
            <button onclick="updateCartItemQty(${index}, 1)" class="w-6 h-6 rounded flex items-center justify-center text-zinc-400 hover:text-white hover:bg-zinc-800 transition font-bold text-xs">+</button>
          </div>
        </td>
        <td class="py-2.5 px-2 text-center">
          <input type="number" min="0" step="any" value="${item.discount_amount || 0}" placeholder="0"
            class="w-14 bg-pitch border border-zinc-800 rounded px-1 py-1 text-center font-mono ${item.discount_amount > 0 ? 'text-red-400 font-bold' : 'text-zinc-400'} text-xs focus:outline-none focus:border-red-400"
            title="Line discount" onchange="updateCartItemDiscount(${index}, this.value)">
        </td>
        <td class="py-2.5 px-3 text-right font-mono font-bold text-emerald-400">
          ${state.settings.currency_symbol || '₹'}${item.line_total.toFixed(2)}
        </td>
        <td class="py-2.5 px-2 text-center">
          <button onclick="removeCartItem(${index})" class="text-zinc-600 hover:text-white p-1 transition" title="Remove item">
            <i class="fa-solid fa-xmark text-sm"></i>
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    }

    // 2. Mobile Touch Cards (Shown on mobile < 640px)
    if (mobileContainer) {
      const card = document.createElement('div');
      card.className = `p-3 rounded-2xl border ${isShortage ? 'border-red-600 bg-red-950/20' : 'border-zinc-850 bg-pitch'} flex flex-col gap-2.5`;
      card.innerHTML = `
        <div class="flex items-start justify-between gap-2.5">
          <div class="flex items-center gap-2.5 min-w-0 flex-1">
            ${item.image_url ? `
              <img src="${item.image_url}" alt="${escapeHtml(item.product_name)}" 
                class="w-11 h-11 object-cover rounded-xl border border-zinc-800 flex-shrink-0 cursor-pointer"
                onclick="openImagePreviewModal('${item.image_url}', '${escapeHtml(item.product_name)}')">
            ` : `
              <div class="w-11 h-11 rounded-xl bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-600 flex-shrink-0">
                <i class="fa-solid fa-shirt text-sm"></i>
              </div>
            `}
            <div class="min-w-0 flex-1">
              <input type="text" value="${escapeHtml(item.product_name)}" 
                class="bg-transparent border-b border-dashed border-zinc-800 hover:border-white focus:border-white focus:bg-black rounded px-1 py-0.5 text-white font-bold w-full text-xs focus:outline-none transition" 
                onchange="updateCartItemName(${index}, this.value)">
              <div class="flex items-center gap-1.5 mt-0.5 text-[10px] text-zinc-400 font-mono flex-wrap">
                <span class="px-1.5 py-0.2 rounded bg-zinc-900 text-zinc-300 font-bold">${item.sku || 'CUSTOM'}</span>
                ${item.size ? `<span class="bg-zinc-900 px-1.5 py-0.2 rounded text-white font-bold">${item.size}</span>` : ''}
                ${item.color ? `<span>${item.color}</span>` : ''}
                ${stockBadge}
              </div>
            </div>
          </div>
          <button onclick="removeCartItem(${index})" class="text-zinc-500 hover:text-red-400 p-1 transition" title="Remove">
            <i class="fa-solid fa-trash-can text-xs"></i>
          </button>
        </div>

        <div class="flex items-center justify-between pt-2 border-t border-zinc-850/60">
          <div class="inline-flex items-center rounded-xl bg-zinc-900 border ${isShortage ? 'border-red-600' : 'border-zinc-800'} p-0.5">
            <button onclick="updateCartItemQty(${index}, -1)" class="w-7 h-7 rounded-lg flex items-center justify-center text-zinc-300 hover:bg-zinc-800 active:scale-95 transition font-bold text-sm">-</button>
            <input type="number" min="1" value="${item.quantity}" 
              class="w-8 bg-transparent text-center font-mono font-bold ${isShortage ? 'text-red-400' : 'text-white'} text-xs focus:outline-none"
              onchange="setCartItemQty(${index}, this.value)">
            <button onclick="updateCartItemQty(${index}, 1)" class="w-7 h-7 rounded-lg flex items-center justify-center text-zinc-300 hover:bg-zinc-800 active:scale-95 transition font-bold text-sm">+</button>
          </div>
          <div class="text-right">
            <div class="text-[10px] text-zinc-500 font-mono">${state.settings.currency_symbol || '₹'}${parseFloat(item.unit_price).toFixed(2)} / unit</div>
            <div class="text-sm font-extrabold text-emerald-400 font-mono">${state.settings.currency_symbol || '₹'}${item.line_total.toFixed(2)}</div>
          </div>
        </div>
      `;
      mobileContainer.appendChild(card);
    }
  });

  // Stock shortage banner and checkout locking
  if (stockAlert && stockAlertMsg) {
    if (hasStockShortage) {
      stockAlertMsg.textContent = `Only ${shortageAvailable} units available for '${shortageItemName}'. Reduce quantity to proceed.`;
      stockAlert.classList.remove('hidden');
      if (checkoutBtn) {
        checkoutBtn.disabled = true;
        checkoutBtn.className = "w-full py-3.5 rounded-xl font-extrabold text-xs tracking-wider uppercase transition flex items-center justify-center gap-2 bg-zinc-800 text-zinc-500 cursor-not-allowed";
        checkoutBtn.innerHTML = `<i class="fa-solid fa-ban"></i><span>STOCK SHORTAGE — CANNOT CHECKOUT</span>`;
      }
      if (mobileCheckoutBtn) {
        mobileCheckoutBtn.disabled = true;
        mobileCheckoutBtn.className = "flex-1 max-w-[210px] py-2.5 px-4 rounded-xl bg-zinc-800 text-zinc-500 font-extrabold text-xs uppercase tracking-wider flex items-center justify-center gap-1.5 cursor-not-allowed";
        mobileCheckoutBtn.innerHTML = `<i class="fa-solid fa-ban text-xs"></i><span>Stock Shortage</span>`;
      }
    } else {
      stockAlert.classList.add('hidden');
      if (checkoutBtn) {
        checkoutBtn.disabled = false;
        checkoutBtn.className = "w-full py-3.5 rounded-xl font-extrabold text-xs tracking-wider uppercase transition flex items-center justify-center gap-2 bg-white hover:bg-zinc-200 text-black shadow-lg cursor-pointer";
        checkoutBtn.innerHTML = `<i class="fa-solid fa-bolt-lightning text-xs"></i><span>COMPLETE SALE & GENERATE BILL</span>`;
      }
      if (mobileCheckoutBtn) {
        mobileCheckoutBtn.disabled = false;
        mobileCheckoutBtn.className = "flex-1 max-w-[210px] py-2.5 px-4 rounded-xl bg-white hover:bg-zinc-200 text-black font-extrabold text-xs uppercase tracking-wider flex items-center justify-center gap-1.5 shadow-lg active:scale-95 transition";
        mobileCheckoutBtn.innerHTML = `<i class="fa-solid fa-bolt-lightning text-xs"></i><span>Complete Sale</span>`;
      }
    }
  }
}

function updateCartItemName(index, newName) {
  if (state.cart[index]) {
    state.cart[index].product_name = newName.trim() || 'Garment Item';
  }
}

function updateCartItemPrice(index, newPrice) {
  const p = parseFloat(newPrice);
  if (!isNaN(p) && p >= 0 && state.cart[index]) {
    state.cart[index].unit_price = p;
    state.cart[index].line_total = Math.max(0, (p * state.cart[index].quantity) - state.cart[index].discount_amount);
    renderCart();
    calculateBillTotals();
  }
}

function updateCartItemQty(index, change) {
  if (state.cart[index]) {
    const item = state.cart[index];
    const newQty = item.quantity + change;
    if (newQty <= 0) {
      removeCartItem(index);
    } else if (item.current_stock !== undefined && newQty > item.current_stock) {
      alert(`Only ${item.current_stock} units available.`);
    } else {
      item.quantity = newQty;
      item.line_total = Math.max(0, (item.unit_price * newQty) - item.discount_amount);
      renderCart();
      calculateBillTotals();
    }
  }
}

function setCartItemQty(index, val) {
  const q = parseInt(val);
  if (state.cart[index]) {
    const item = state.cart[index];
    if (isNaN(q) || q <= 0) {
      item.quantity = 1;
    } else if (item.current_stock !== undefined && q > item.current_stock) {
      alert(`Only ${item.current_stock} units available.`);
      item.quantity = item.current_stock;
    } else {
      item.quantity = q;
    }
    item.line_total = Math.max(0, (item.unit_price * item.quantity) - item.discount_amount);
    renderCart();
    calculateBillTotals();
  }
}

function updateCartItemDiscount(index, discVal) {
  const d = parseFloat(discVal) || 0;
  if (state.cart[index] && d >= 0) {
    state.cart[index].discount_amount = d;
    state.cart[index].line_total = Math.max(0, (state.cart[index].unit_price * state.cart[index].quantity) - d);
    renderCart();
    calculateBillTotals();
  }
}

function removeCartItem(index) {
  state.cart.splice(index, 1);
  renderCart();
  calculateBillTotals();
}

function clearCart() {
  if (state.cart.length === 0) return;
  if (confirm('Clear current bill items?')) {
    state.cart = [];
    state.discountVal = 0;
    document.getElementById('order-discount-input').value = '0';
    hideSuccessViewAndShowCart();
    renderCart();
    calculateBillTotals();
    const scanInput = document.getElementById('barcode-scan-input');
    if (scanInput) scanInput.focus();
  }
}

// ==============================================================
// 6. TOTALS, TAX, DISCOUNT, & PAYMENT CALCULATION
// ==============================================================

function setDiscountType(type) {
  state.discountType = type;
  const fixedBtn = document.getElementById('disc-type-fixed');
  const pctBtn = document.getElementById('disc-type-percent');
  if (type === 'fixed') {
    fixedBtn.className = 'px-1.5 py-0.2 rounded font-bold bg-white text-black';
    pctBtn.className = 'px-1.5 py-0.2 rounded text-zinc-400';
  } else {
    pctBtn.className = 'px-1.5 py-0.2 rounded font-bold bg-white text-black';
    fixedBtn.className = 'px-1.5 py-0.2 rounded text-zinc-400';
  }
  calculateBillTotals();
}

function applyQuickDiscount(val, isPercent = false) {
  if (isPercent) {
    setDiscountType('percent');
  } else {
    setDiscountType('fixed');
  }
  state.discountVal = val;
  document.getElementById('order-discount-input').value = val;
  calculateBillTotals();
}

function calculateBillTotals() {
  const subtotal = state.cart.reduce((sum, it) => sum + it.line_total, 0);
  
  const discountInput = parseFloat(document.getElementById('order-discount-input').value) || 0;
  state.discountVal = discountInput;
  let discountAmount = 0;
  if (state.discountType === 'percent') {
    discountAmount = (subtotal * discountInput) / 100;
  } else {
    discountAmount = discountInput;
  }
  discountAmount = Math.min(subtotal, Math.max(0, discountAmount));

  const taxRate = parseFloat(document.getElementById('tax-rate-select').value) || 0;
  state.taxRate = taxRate;
  const taxableAmount = Math.max(0, subtotal - discountAmount);
  const taxAmount = (taxableAmount * taxRate) / 100;

  const grandTotal = Math.round((taxableAmount + taxAmount) * 100) / 100;

  document.getElementById('bill-subtotal').textContent = subtotal.toFixed(2);
  document.getElementById('bill-discount-amount').textContent = discountAmount.toFixed(2);
  document.getElementById('bill-tax-amount').textContent = taxAmount.toFixed(2);
  document.getElementById('bill-grand-total').textContent = grandTotal.toFixed(2);

  const mobileBottomTotal = document.getElementById('mobile-bottom-total');
  if (mobileBottomTotal) mobileBottomTotal.textContent = grandTotal.toFixed(2);

  if (state.paymentMethod === 'UPI' && grandTotal > 0) {
    renderDynamicUPIQR(grandTotal);
  }

  calculateChange();
}

function setPaymentMethod(method) {
  state.paymentMethod = method;
  document.querySelectorAll('.pay-method-btn').forEach(btn => {
    btn.className = 'pay-method-btn py-2 rounded-xl text-xs font-bold border border-zinc-800 bg-pitch text-zinc-300 hover:text-white hover:border-zinc-600 flex flex-col items-center gap-1 transition';
  });

  const activeBtn = document.getElementById(`pay-btn-${method}`);
  if (activeBtn) {
    activeBtn.className = 'pay-method-btn active py-2 rounded-xl text-xs font-extrabold border border-white bg-white text-black flex flex-col items-center gap-1 transition';
  }

  const cashBox = document.getElementById('cash-calculator-box');
  const upiBox = document.getElementById('upi-qr-box');

  if (method === 'Cash') {
    cashBox.classList.remove('hidden');
    upiBox.classList.add('hidden');
  } else if (method === 'UPI') {
    cashBox.classList.add('hidden');
    upiBox.classList.remove('hidden');
    const grandTotal = parseFloat(document.getElementById('bill-grand-total').textContent) || 0;
    renderDynamicUPIQR(grandTotal);
  } else {
    cashBox.classList.add('hidden');
    upiBox.classList.add('hidden');
  }
}

function renderDynamicUPIQR(amount) {
  const container = document.getElementById('dynamic-upi-qrcode');
  if (!container) return;
  container.innerHTML = '';
  
  const upiId = state.settings.upi_id || 'sol@upi';
  const storeName = state.settings.store_name || 'SOL';
  const upiUri = `upi://pay?pa=${encodeURIComponent(upiId)}&pn=${encodeURIComponent(storeName)}&am=${amount.toFixed(2)}&cu=INR`;

  new QRCode(container, {
    text: upiUri,
    width: 128,
    height: 128,
    colorDark: "#000000",
    colorLight: "#ffffff",
    correctLevel: QRCode.CorrectLevel.M
  });
}

function calculateChange() {
  const grandTotal = parseFloat(document.getElementById('bill-grand-total').textContent) || 0;
  const tendered = parseFloat(document.getElementById('cash-tendered-input').value) || 0;
  state.cashTendered = tendered;
  const change = Math.max(0, tendered - grandTotal);
  document.getElementById('cash-change-due').textContent = change.toFixed(2);
}

function setCashTendered(val) {
  if (val === 'exact') {
    const grandTotal = parseFloat(document.getElementById('bill-grand-total').textContent) || 0;
    document.getElementById('cash-tendered-input').value = Math.ceil(grandTotal);
  }
  calculateChange();
}

function addCashTendered(amount) {
  const current = parseFloat(document.getElementById('cash-tendered-input').value) || 0;
  document.getElementById('cash-tendered-input').value = current + amount;
  calculateChange();
}

// ==============================================================
// 7. CUSTOMER CRM SELECTION & DISCOUNTS
// ==============================================================

async function loadCustomers() {
  try {
    const res = await fetch('/api/customers');
    if (res.ok) {
      state.allCustomers = await res.json();
    }
  } catch (err) {
    console.error('Failed to load customers:', err);
  }
}

let customerSearchTimeout = null;

async function handleCustomerSearchInput(val) {
  const dropdown = document.getElementById('customer-dropdown');
  const clearBtn = document.getElementById('clear-cust-btn');
  const term = val.trim();

  if (!term) {
    dropdown.classList.add('hidden');
    clearBtn.classList.add('hidden');
    return;
  }

  clearBtn.classList.remove('hidden');

  if (customerSearchTimeout) clearTimeout(customerSearchTimeout);

  customerSearchTimeout = setTimeout(async () => {
    let matches = [];
    try {
      const res = await fetch(`/api/customers/search?q=${encodeURIComponent(term)}`);
      if (res.ok) {
        matches = await res.json();
      }
    } catch (e) {
      console.warn('Customer search API error, falling back:', e);
    }

    if (matches.length === 0 && state.allCustomers && state.allCustomers.length > 0) {
      const lower = term.toLowerCase();
      matches = state.allCustomers.filter(c => 
        (c.name && c.name.toLowerCase().includes(lower)) || 
        (c.phone && c.phone.includes(lower)) ||
        (c.email && c.email.toLowerCase().includes(lower))
      );
    }

    dropdown.innerHTML = '';
    const currency = state.settings.currency_symbol || '₹';

    if (matches.length > 0) {
      matches.slice(0, 6).forEach(c => {
        const item = document.createElement('div');
        item.className = 'p-2.5 hover:bg-zinc-800 cursor-pointer border-b border-zinc-800 text-xs transition flex flex-col gap-1';
        item.onclick = () => selectCustomer(c);

        const lastVisitStr = c.last_visit ? new Date(c.last_visit).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) : 'Never';

        item.innerHTML = `
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="font-bold text-white">${escapeHtml(c.name)}</span>
              <span class="text-zinc-400 font-mono text-[11px]">${escapeHtml(c.phone)}</span>
              ${c.email ? `<span class="text-zinc-500 text-[10px] hidden sm:inline">&lt;${escapeHtml(c.email)}&gt;</span>` : ''}
            </div>
            <div class="flex items-center gap-1.5">
              <span class="text-[9px] font-extrabold uppercase px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">${c.tier || 'BRONZE'}</span>
              ${c.suggested_discount ? `<span class="text-[9px] font-extrabold text-emerald-400 bg-emerald-950 px-1 py-0.5 rounded border border-emerald-800">-${c.suggested_discount}%</span>` : ''}
            </div>
          </div>
          <div class="flex items-center justify-between text-[10px] text-zinc-500">
            <span>Orders: <strong class="text-zinc-300 font-mono">${c.total_orders || 0}</strong> • Spent: <strong class="text-zinc-300 font-mono">${currency}${parseFloat(c.total_spent || 0).toFixed(0)}</strong></span>
            <span>Last visit: <strong class="text-zinc-400">${lastVisitStr}</strong></span>
          </div>
        `;
        dropdown.appendChild(item);
      });
    }

    // Always provide quick add "+ New Customer" button at the bottom
    const addNewItem = document.createElement('div');
    addNewItem.className = 'p-2.5 hover:bg-zinc-800 text-emerald-400 font-bold cursor-pointer text-xs flex items-center justify-between border-t border-zinc-800 transition';
    addNewItem.onclick = () => {
      openNewCustomerModal(term);
      dropdown.classList.add('hidden');
    };
    addNewItem.innerHTML = `
      <span class="flex items-center gap-1.5">
        <i class="fa-solid fa-user-plus text-xs"></i>
        <span>+ New Customer "${escapeHtml(term)}"</span>
      </span>
      <span class="text-[10px] uppercase font-mono text-zinc-500">Quick Create</span>
    `;
    dropdown.appendChild(addNewItem);

    dropdown.classList.remove('hidden');
  }, 120);
}

function selectCustomer(cust) {
  state.selectedCustomer = cust;
  document.getElementById('billing-customer-search').value = `${cust.name} (${cust.phone})`;
  document.getElementById('customer-dropdown').classList.add('hidden');
  document.getElementById('clear-cust-btn').classList.remove('hidden');

  document.getElementById('active-cust-name').textContent = cust.name;
  
  const phoneEmail = [cust.phone, cust.email].filter(Boolean).join(' • ');
  document.getElementById('active-cust-phone').textContent = phoneEmail || 'No phone attached';
  
  const lastPurchase = cust.last_visit ? ` • Last: ${new Date(cust.last_visit).toLocaleDateString([], { month: 'short', day: 'numeric' })}` : '';
  document.getElementById('active-cust-orders').textContent = `• ${cust.total_orders || 0} orders (${state.settings.currency_symbol || '₹'}${parseFloat(cust.total_spent || 0).toFixed(0)})${lastPurchase}`;
  
  const tierBadge = document.getElementById('active-cust-tier');
  tierBadge.textContent = (cust.tier || 'BRONZE').toUpperCase();

  const discPill = document.getElementById('active-cust-discount-pill');
  const discBtn = document.getElementById('active-cust-discount-btn');
  if (cust.suggested_discount && cust.suggested_discount > 0) {
    discBtn.textContent = `Apply ${cust.suggested_discount}%`;
    discPill.classList.remove('hidden');
  } else {
    discPill.classList.add('hidden');
  }

  // Refocus scan input for continuous cashier flow
  const scanInput = document.getElementById('barcode-scan-input');
  if (scanInput) scanInput.focus();
}

function clearSelectedCustomer() {
  state.selectedCustomer = null;
  document.getElementById('billing-customer-search').value = '';
  document.getElementById('customer-dropdown').classList.add('hidden');
  document.getElementById('clear-cust-btn').classList.add('hidden');

  document.getElementById('active-cust-name').textContent = 'Walk-in Guest';
  document.getElementById('active-cust-phone').textContent = 'No phone attached';
  document.getElementById('active-cust-orders').textContent = '• 0 orders';
  
  const tierBadge = document.getElementById('active-cust-tier');
  tierBadge.textContent = 'GUEST';
  document.getElementById('active-cust-discount-pill').classList.add('hidden');

  const scanInput = document.getElementById('barcode-scan-input');
  if (scanInput) scanInput.focus();
}

function applyVIPTierDiscount() {
  if (state.selectedCustomer && state.selectedCustomer.suggested_discount) {
    applyQuickDiscount(state.selectedCustomer.suggested_discount, true);
    playBeep(880, 0.1);
  }
}

// ==============================================================
// 8. COMPLETE SALE & BILL GENERATION
// ==============================================================

async function completeSaleAndGenerateBill() {
  if (state.cart.length === 0) {
    alert('Please add at least one garment style to the bill.');
    return;
  }

  // Check if any cart item has quantity > current_stock
  const shortageItem = state.cart.find(it => it.current_stock !== undefined && it.quantity > it.current_stock);
  if (shortageItem) {
    alert(`Only ${shortageItem.current_stock} units available for '${shortageItem.product_name}'. Reduce quantity to proceed.`);
    return;
  }

  const grandTotal = parseFloat(document.getElementById('bill-grand-total').textContent) || 0;
  const rawSearch = document.getElementById('billing-customer-search') ? document.getElementById('billing-customer-search').value.trim() : '';

  // If customer is already selected or typed into the CRM search field, proceed directly
  if (state.selectedCustomer || (rawSearch && rawSearch !== 'Walk-in Guest')) {
    await executeCheckoutTransaction();
    return;
  }

  // Otherwise, prompt cashier for customer mobile & WhatsApp receipt
  openCustomerCheckoutPromptModal(grandTotal);
}

function openCustomerCheckoutPromptModal(grandTotal) {
  const modal = document.getElementById('modal-customer-checkout-prompt');
  if (!modal) return;

  const totalEl = document.getElementById('prompt-grand-total');
  if (totalEl) totalEl.textContent = (grandTotal !== undefined ? grandTotal : (parseFloat(document.getElementById('bill-grand-total').textContent) || 0)).toFixed(2);

  const phoneInput = document.getElementById('prompt-cust-phone');
  const nameInput = document.getElementById('prompt-cust-name');
  const matchedPill = document.getElementById('prompt-matched-customer-pill');

  if (phoneInput) phoneInput.value = '';
  if (nameInput) nameInput.value = '';
  if (matchedPill) matchedPill.classList.add('hidden');

  modal.classList.remove('hidden');
  setTimeout(() => {
    if (phoneInput) phoneInput.focus();
  }, 100);
}

function closeCustomerCheckoutPromptModal() {
  const modal = document.getElementById('modal-customer-checkout-prompt');
  if (modal) modal.classList.add('hidden');
}

function handlePromptPhoneInput(val) {
  const phone = val.trim();
  const matchedPill = document.getElementById('prompt-matched-customer-pill');
  const matchedName = document.getElementById('prompt-matched-name');
  const matchedTier = document.getElementById('prompt-matched-tier');
  const nameInput = document.getElementById('prompt-cust-name');

  if (!phone || phone.length < 3) {
    if (matchedPill) matchedPill.classList.add('hidden');
    return;
  }

  const cleanInput = phone.replace(/\D/g, '');
  const found = (state.allCustomers || []).find(c => {
    const cPhone = (c.phone || '').replace(/\D/g, '');
    return cPhone && (cPhone.endsWith(cleanInput) || cleanInput.endsWith(cPhone));
  });

  if (found) {
    if (matchedPill) matchedPill.classList.remove('hidden');
    if (matchedName) matchedName.textContent = found.name;
    if (matchedTier) matchedTier.textContent = (found.tier || 'BRONZE').toUpperCase();
    if (nameInput && !nameInput.value) {
      nameInput.value = found.name;
    }
  } else {
    if (matchedPill) matchedPill.classList.add('hidden');
  }
}

async function confirmCustomerAndCompleteSale() {
  const phoneInput = document.getElementById('prompt-cust-phone');
  const nameInput = document.getElementById('prompt-cust-name');

  const phone = phoneInput ? phoneInput.value.trim() : '';
  const name = nameInput ? nameInput.value.trim() : '';

  if (!phone) {
    alert('Please enter a customer mobile number, or click "Skip — Proceed as Walk-in Guest".');
    if (phoneInput) phoneInput.focus();
    return;
  }

  closeCustomerCheckoutPromptModal();
  await executeCheckoutTransaction({
    phone: phone,
    name: name || `Customer (${phone.slice(-4)})`
  });
}

async function skipCustomerAndCompleteSale() {
  closeCustomerCheckoutPromptModal();
  await executeCheckoutTransaction({
    phone: '',
    name: 'Walk-in Guest'
  });
}

async function executeCheckoutTransaction(customerOverride = null) {
  const subtotal = state.cart.reduce((sum, it) => sum + it.line_total, 0);
  const discountAmount = parseFloat(document.getElementById('bill-discount-amount').textContent) || 0;
  const taxAmount = parseFloat(document.getElementById('bill-tax-amount').textContent) || 0;
  const grandTotal = parseFloat(document.getElementById('bill-grand-total').textContent) || 0;
  const notes = document.getElementById('bill-notes-input') ? document.getElementById('bill-notes-input').value.trim() : '';

  let tendered = state.cashTendered;
  let returned = 0;
  if (state.paymentMethod === 'Cash') {
    if (tendered > 0 && tendered < grandTotal) {
      alert(`Cash tendered (${state.settings.currency_symbol || '₹'}${tendered}) is less than the Grand Total (${state.settings.currency_symbol || '₹'}${grandTotal}).`);
      return;
    }
    if (tendered >= grandTotal) {
      returned = tendered - grandTotal;
    } else if (tendered === 0) {
      tendered = grandTotal;
    }
  }

  let custName = 'Walk-in Guest';
  let custPhone = '';
  let custEmail = '';
  let custId = null;

  if (customerOverride) {
    custName = customerOverride.name || 'Walk-in Guest';
    custPhone = customerOverride.phone || '';
    const cleanP = custPhone.replace(/\D/g, '');
    const found = cleanP ? (state.allCustomers || []).find(c => (c.phone || '').replace(/\D/g, '') === cleanP) : null;
    if (found) {
      custId = found.id;
      custEmail = found.email || '';
    }
  } else if (state.selectedCustomer) {
    custId = state.selectedCustomer.id;
    custName = state.selectedCustomer.name;
    custPhone = state.selectedCustomer.phone;
    custEmail = state.selectedCustomer.email || '';
  } else {
    const rawSearch = document.getElementById('billing-customer-search') ? document.getElementById('billing-customer-search').value.trim() : '';
    if (rawSearch) {
      if (/^\+?[0-9\s-]{7,15}$/.test(rawSearch)) {
        custPhone = rawSearch;
        custName = `Customer (${rawSearch.slice(-4)})`;
      } else {
        custName = rawSearch;
      }
    }
  }

  const payload = {
    customer_id: custId,
    customer_name: custName,
    customer_phone: custPhone,
    customer_email: custEmail,
    items: state.cart.map(it => ({
      product_id: it.product_id,
      variant_id: it.variant_id || null,
      sku: it.sku || '',
      barcode: it.barcode || '',
      product_name: it.product_name,
      size: it.size || '',
      color: it.color || '',
      unit_price: it.unit_price,
      quantity: it.quantity,
      discount_amount: it.discount_amount || 0.0,
      line_total: it.line_total
    })),
    subtotal: subtotal,
    discount_type: state.discountType,
    discount_val: state.discountVal,
    discount_amount: discountAmount,
    tax_rate: state.taxRate,
    tax_amount: taxAmount,
    grand_total: grandTotal,
    payment_method: state.paymentMethod,
    payment_status: 'Paid',
    cash_tendered: tendered,
    change_returned: returned,
    notes: notes
  };

  const checkoutBtn = document.getElementById('checkout-btn');
  const mobileCheckoutBtn = document.getElementById('mobile-checkout-btn');

  if (checkoutBtn) {
    checkoutBtn.disabled = true;
    checkoutBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Processing & Syncing...`;
  }
  if (mobileCheckoutBtn) {
    mobileCheckoutBtn.disabled = true;
    mobileCheckoutBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-xs"></i><span>Processing...</span>`;
  }

  try {
    const res = await fetch('/api/invoices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to complete invoice');
    }

    const createdSale = await res.json();
    state.lastCompletedInvoice = createdSale;

    if (window.confetti) {
      window.confetti({ particleCount: 60, spread: 50, origin: { y: 0.8 }, colors: ['#ffffff', '#888888', '#000000'] });
    }
    playSuccessChime();

    // Clear cart & input state
    state.cart = [];
    state.discountVal = 0;
    state.cashTendered = 0;
    const discInput = document.getElementById('order-discount-input');
    if (discInput) discInput.value = '0';
    const notesInput = document.getElementById('bill-notes-input');
    if (notesInput) notesInput.value = '';
    const cashInput = document.getElementById('cash-tendered-input');
    if (cashInput) cashInput.value = '';
    const changeDueEl = document.getElementById('cash-change-due');
    if (changeDueEl) changeDueEl.textContent = `${state.settings.currency_symbol || '₹'}0.00`;
    clearSelectedCustomer();
    renderCart();
    calculateBillTotals();

    // Show Compact Success Screen replacing Cart (Requirement 9)
    showSuccessStateView(createdSale);

    // Refresh background inventory, CRM, and sold products stats
    loadProducts();
    loadCustomers();
    loadSoldProductsModal();

  } catch (err) {
    alert('Billing Error: ' + err.message);
  } finally {
    if (checkoutBtn) {
      checkoutBtn.disabled = false;
      checkoutBtn.className = "w-full py-3.5 rounded-xl font-extrabold text-xs tracking-wider uppercase transition flex items-center justify-center gap-2 bg-white hover:bg-zinc-200 text-black shadow-lg cursor-pointer";
      checkoutBtn.innerHTML = `<i class="fa-solid fa-bolt-lightning text-xs"></i><span>COMPLETE SALE & GENERATE BILL</span>`;
    }
    if (mobileCheckoutBtn) {
      mobileCheckoutBtn.disabled = false;
      mobileCheckoutBtn.className = "flex-1 max-w-[210px] py-2.5 px-4 rounded-xl bg-white hover:bg-zinc-200 text-black font-extrabold text-xs uppercase tracking-wider flex items-center justify-center gap-1.5 shadow-lg active:scale-95 transition";
      mobileCheckoutBtn.innerHTML = `<i class="fa-solid fa-bolt-lightning text-xs"></i><span>Complete Sale</span>`;
    }
  }
}

// ==============================================================
// 9. INVOICE DISPLAY, THERMAL PRINT, WHATSAPP & GMAIL
// ==============================================================

function openInvoiceSuccessModal(inv) {
  document.getElementById('modal-inv-id').textContent = inv.invoice_number;
  renderThermalReceiptView(inv);
  document.getElementById('modal-invoice-success').classList.remove('hidden');
}

function closeInvoiceSuccessModal() {
  document.getElementById('modal-invoice-success').classList.add('hidden');
}

function renderThermalReceiptView(inv) {
  const container = document.getElementById('printable-receipt-container');
  const s = state.settings;
  const dateStr = new Date(inv.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });

  let itemsHtml = '';
  inv.items.forEach(it => {
    itemsHtml += `
      <div style="margin-bottom: 5px;">
        <div style="display: flex; justify-content: space-between; font-weight: 700;">
          <span>${escapeHtml(it.product_name)}</span>
          <span>${s.currency_symbol}${it.line_total.toFixed(2)}</span>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 10px; color: #444;">
          <span>${it.size ? it.size + ' ' : ''}${it.color ? it.color + ' ' : ''}(${it.quantity} x ${s.currency_symbol}${it.unit_price})</span>
          ${it.discount_amount > 0 ? `<span>Disc: -${s.currency_symbol}${it.discount_amount}</span>` : ''}
        </div>
      </div>
    `;
  });

  container.innerHTML = `
    <!-- Top SOL Logo & Header -->
    <div style="text-align: center; margin-bottom: 12px;">
      <img src="/static/sol_logo_black.svg" alt="SOL Soul of Lifestyle" style="max-height: 50px; width: auto; margin: 0 auto 6px auto; display: block;">
      <p style="font-size: 9px; margin: 3px 0;">${escapeHtml(s.address || '')}</p>
      <p style="font-size: 9px; margin: 1px 0;">Tel: ${escapeHtml(s.phone || '')} | GSTIN: ${escapeHtml(s.gstin || '')}</p>
      <div style="border-top: 1px solid #000; margin: 8px 0;"></div>
      <div style="display: flex; justify-content: space-between; font-size: 10.5px;">
        <span><strong>${inv.invoice_number}</strong></span>
        <span>${dateStr}</span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 10px; margin-top: 2px;">
        <span>Customer: ${escapeHtml(inv.customer_name)}</span>
        <span>${inv.customer_phone || ''}</span>
      </div>
      <div style="border-top: 1px solid #000; margin: 8px 0;"></div>
    </div>

    <!-- Items List -->
    <div style="margin-bottom: 8px;">
      ${itemsHtml}
    </div>

    <div style="border-top: 1px solid #000; margin: 8px 0;"></div>

    <!-- Totals -->
    <div style="font-size: 11px; line-height: 1.5;">
      <div style="display: flex; justify-content: space-between;">
        <span>Subtotal</span>
        <span>${s.currency_symbol}${inv.subtotal.toFixed(2)}</span>
      </div>
      ${inv.discount_amount > 0 ? `
      <div style="display: flex; justify-content: space-between;">
        <span>Discount</span>
        <span>-${s.currency_symbol}${inv.discount_amount.toFixed(2)}</span>
      </div>` : ''}
      ${inv.tax_amount > 0 ? `
      <div style="display: flex; justify-content: space-between;">
        <span>GST (${inv.tax_rate}%)</span>
        <span>+${s.currency_symbol}${inv.tax_amount.toFixed(2)}</span>
      </div>` : ''}
      <div style="border-top: 1.5px solid #000; margin: 5px 0;"></div>
      <div style="display: flex; justify-content: space-between; font-size: 13.5px; font-weight: 800;">
        <span>TOTAL</span>
        <span>${s.currency_symbol}${inv.grand_total.toFixed(2)}</span>
      </div>
      <div style="border-top: 1.5px solid #000; margin: 5px 0;"></div>
      <div style="display: flex; justify-content: space-between; font-size: 10px;">
        <span>Payment: <strong>${inv.payment_method}</strong></span>
        <span>Status: <strong>PAID</strong></span>
      </div>
      ${inv.payment_method === 'Cash' && inv.cash_tendered > 0 ? `
      <div style="display: flex; justify-content: space-between; font-size: 10px;">
        <span>Cash Tendered: ${s.currency_symbol}${inv.cash_tendered.toFixed(2)}</span>
        <span>Change Returned: ${s.currency_symbol}${inv.change_returned.toFixed(2)}</span>
      </div>` : ''}
    </div>

    <div style="border-top: 1px dashed #000; margin: 12px 0 8px 0;"></div>

    <!-- Footer & Return Policy -->
    <div style="text-align: center; font-size: 9px; color: #222;">
      <p style="margin: 2px 0; font-weight: 800; letter-spacing: 1px;">ELEVATE YOUR STYLE • SOL</p>
      <p style="margin: 2px 0; font-size: 8px;">${escapeHtml(s.return_policy || '')}</p>
      <div id="receipt-qr-code" style="display: flex; justify-content: center; margin: 8px 0;"></div>
      <p style="font-size: 7.5px; color: #666; font-family: monospace;">SOL POS • FAST APPAREL ENGINE</p>
    </div>
  `;

  setTimeout(() => {
    const qrContainer = document.getElementById('receipt-qr-code');
    if (qrContainer) {
      qrContainer.innerHTML = '';
      new QRCode(qrContainer, {
        text: `SOL-INV:${inv.invoice_number}|AMT:${inv.grand_total}`,
        width: 60,
        height: 60,
        colorDark: "#000000",
        colorLight: "#ffffff",
        correctLevel: QRCode.CorrectLevel.M
      });
    }
  }, 80);
}

function printThermalReceipt() {
  window.print();
}

function printA4Invoice() {
  const inv = state.lastCompletedInvoice;
  if (inv && inv.id) {
    downloadInvoicePDF(inv.id);
  } else {
    window.print();
  }
}

function downloadInvoicePDF(invId) {
  const id = invId || (state.lastCompletedInvoice ? state.lastCompletedInvoice.id : null);
  if (!id) {
    alert('No invoice available for download.');
    return;
  }
  window.open(`/api/invoices/${id}/pdf`, '_blank');
}

// Compact Success View (Requirement 9)
function showSuccessStateView(sale) {
  const currency = state.settings.currency_symbol || '₹';
  
  // Hide cart table, placeholder and stock alert
  const tableView = document.getElementById('cart-table-view');
  const emptyView = document.getElementById('cart-empty-placeholder');
  const stockAlert = document.getElementById('cart-stock-alert');
  const successView = document.getElementById('cart-success-view');

  if (tableView) tableView.classList.add('hidden');
  if (emptyView) emptyView.classList.add('hidden');
  if (stockAlert) stockAlert.classList.add('hidden');
  if (successView) successView.classList.remove('hidden');

  // Fill in sale details
  const grandTotalEl = document.getElementById('success-grand-total');
  if (grandTotalEl) grandTotalEl.textContent = `${currency}${parseFloat(sale.grand_total || 0).toFixed(2)}`;

  const invNumEl = document.getElementById('success-inv-number');
  if (invNumEl) invNumEl.textContent = sale.invoice_number;

  const payMethodEl = document.getElementById('success-payment-method');
  if (payMethodEl) payMethodEl.textContent = sale.payment_method;

  const waStatusEl = document.getElementById('success-wa-status');
  if (waStatusEl) {
    if (sale.whatsapp_status === 'SENT') {
      waStatusEl.textContent = '✓ Sent';
      waStatusEl.className = 'font-semibold text-emerald-400 text-xs';
    } else if (sale.customer_phone) {
      waStatusEl.textContent = 'Ready';
      waStatusEl.className = 'font-semibold text-zinc-300 text-xs';
    } else {
      waStatusEl.textContent = 'No Phone';
      waStatusEl.className = 'font-semibold text-zinc-500 text-xs';
    }
  }

  const emailStatusEl = document.getElementById('success-email-status');
  if (emailStatusEl) {
    if (sale.email_status === 'SENT') {
      emailStatusEl.textContent = '✓ Sent';
      emailStatusEl.className = 'font-semibold text-emerald-400 text-xs';
    } else if (sale.customer_email) {
      emailStatusEl.textContent = 'Ready';
      emailStatusEl.className = 'font-semibold text-zinc-300 text-xs';
    } else {
      emailStatusEl.textContent = 'No Email';
      emailStatusEl.className = 'font-semibold text-zinc-500 text-xs';
    }
  }

  // Setup WhatsApp button link
  const waBtn = document.getElementById('success-wa-btn');
  if (waBtn) {
    waBtn.href = sale.whatsapp_url || getWhatsAppShareUrl(sale);
  }

  // Update Cart badge to 0 items
  const badge = document.getElementById('cart-item-count-badge');
  if (badge) badge.textContent = '0 items';
}

function hideSuccessViewAndShowCart() {
  const successView = document.getElementById('cart-success-view');
  if (successView) successView.classList.add('hidden');

  const tableView = document.getElementById('cart-table-view');
  const emptyView = document.getElementById('cart-empty-placeholder');

  if (state.cart.length > 0) {
    if (tableView) tableView.classList.remove('hidden');
    if (emptyView) emptyView.classList.add('hidden');
  } else {
    if (tableView) tableView.classList.add('hidden');
    if (emptyView) emptyView.classList.remove('hidden');
  }
}

function resetPosForNewSale() {
  state.cart = [];
  state.discountVal = 0;
  state.cashTendered = 0;
  
  const discInput = document.getElementById('order-discount-input');
  if (discInput) discInput.value = '0';
  const notesInput = document.getElementById('bill-notes-input');
  if (notesInput) notesInput.value = '';
  const cashInput = document.getElementById('cash-tendered-input');
  if (cashInput) cashInput.value = '';
  const changeEl = document.getElementById('cash-change-due');
  if (changeEl) changeEl.textContent = `${state.settings.currency_symbol || '₹'}0.00`;

  clearSelectedCustomer();
  hideSuccessViewAndShowCart();
  renderCart();
  calculateBillTotals();

  // Focus scan input for continuous cashier speed
  const scanInput = document.getElementById('barcode-scan-input');
  if (scanInput) scanInput.focus();
}

function printLastThermalReceipt() {
  if (!state.lastCompletedInvoice) {
    alert('No recent bill found to print.');
    return;
  }
  renderThermalReceiptView(state.lastCompletedInvoice);
  window.print();
}

function openLastBillModal() {
  if (!state.lastCompletedInvoice) {
    alert('No recent bill found.');
    return;
  }
  openInvoiceSuccessModal(state.lastCompletedInvoice);
}

async function retryLastEmailDelivery() {
  if (!state.lastCompletedInvoice) {
    alert('No recent invoice available.');
    return;
  }
  const sale = state.lastCompletedInvoice;
  const emailStatusEl = document.getElementById('success-email-status');
  if (emailStatusEl) emailStatusEl.textContent = 'Sending...';

  try {
    const res = await fetch(`/api/invoices/${sale.id}/retry-delivery`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel: 'EMAIL' })
    });
    if (res.ok) {
      if (emailStatusEl) {
        emailStatusEl.textContent = '✓ Sent';
        emailStatusEl.className = 'font-semibold text-emerald-400 text-xs';
      }
      alert('Invoice email dispatched successfully!');
    } else {
      openGmailReceiptCompose();
    }
  } catch (err) {
    openGmailReceiptCompose();
  }
}

function getWhatsAppShareUrl(inv) {
  if (!inv) return '#';
  const s = state.settings;
  const currency = s.currency_symbol || '₹';
  const cleanPhone = (inv.customer_phone || '').replace(/[^0-9]/g, '');

  let itemLines = '';
  (inv.items || []).forEach((it, idx) => {
    const variant = [it.size, it.color].filter(Boolean).join('/');
    const variantStr = variant ? ` (${variant})` : '';
    itemLines += `${idx + 1}. *${it.product_name}*${variantStr} x ${it.quantity} = ${currency}${it.line_total.toFixed(2)}\n`;
  });

  const message = `✦ *SOL • SOUL OF LIFESTYLE* ✦
_PREMIUM WEAR | MODERN ESSENTIALS | ELEVATED YOU_

📄 *INVOICE:* ${inv.invoice_number}
👤 *CUSTOMER:* ${inv.customer_name}
📅 *DATE:* ${new Date(inv.created_at || Date.now()).toLocaleDateString()}

*ITEMS PURCHASED:*
${itemLines}
------------------------------------
*SUBTOTAL:* ${currency}${inv.subtotal.toFixed(2)}
${inv.discount_amount > 0 ? `*DISCOUNT:* -${currency}${inv.discount_amount.toFixed(2)}\n` : ''}${inv.tax_amount > 0 ? `*GST / TAX (${inv.tax_rate}%):* +${currency}${inv.tax_amount.toFixed(2)}\n` : ''}*GRAND TOTAL PAID:* ${currency}${inv.grand_total.toFixed(2)} (${inv.payment_method})
------------------------------------
🏷️ *RETURN POLICY:*
${s.return_policy || 'Exchange within 7 days with invoice & tags intact.'}

Thank you for choosing SOL. Elevate your style. ✨`;

  const encoded = encodeURIComponent(message);
  if (cleanPhone && cleanPhone.length >= 10) {
    return `https://wa.me/${cleanPhone}?text=${encoded}`;
  }
  return `https://wa.me/?text=${encoded}`;
}

// 📲 Luxury WhatsApp E-Receipt Delivery
function shareInvoiceViaWhatsApp() {
  const inv = state.lastCompletedInvoice;
  if (!inv) return;
  const url = getWhatsAppShareUrl(inv);
  window.open(url, '_blank');
}

// ✉️ Gmail Direct Compose or Web Link
function openGmailReceiptCompose() {
  const inv = state.lastCompletedInvoice;
  if (!inv) return;

  const s = state.settings;
  const currency = s.currency_symbol || '₹';
  const custEmail = (inv.customer_email || (state.selectedCustomer ? state.selectedCustomer.email : '') || '').trim();

  let itemLines = '';
  inv.items.forEach((it, idx) => {
    const variant = [it.size, it.color].filter(Boolean).join('/');
    itemLines += `${idx + 1}. ${it.product_name} (${variant || '-'}) x ${it.quantity} = ${currency}${it.line_total.toFixed(2)}\n`;
  });

  const subject = `Your E-Receipt for Invoice ${inv.invoice_number} - SOL Soul of Lifestyle`;
  const body = `Dear ${inv.customer_name},

Thank you for choosing SOL • Soul of Lifestyle.

INVOICE SUMMARY:
--------------------------------------
Invoice Number: ${inv.invoice_number}
Date: ${new Date(inv.created_at).toLocaleDateString()}

Items:
${itemLines}
--------------------------------------
Subtotal: ${currency}${inv.subtotal.toFixed(2)}
Discount: -${currency}${inv.discount_amount.toFixed(2)}
GST / Tax: +${currency}${inv.tax_amount.toFixed(2)}
Total Paid: ${currency}${inv.grand_total.toFixed(2)} (via ${inv.payment_method})
--------------------------------------

Return / Exchange Policy:
${s.return_policy || 'Exchange within 7 days with tags and bill intact.'}

SOL • Soul of Lifestyle
${s.address || ''}
${s.phone || ''}
`;

  // Open Gmail Web Compose directly
  const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(custEmail)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  window.open(gmailUrl, '_blank');
}

// ==============================================================
// 10. PRODUCT CATALOG & INVENTORY MANAGEMENT
// ==============================================================

async function loadProducts() {
  try {
    const res = await fetch('/api/products');
    if (res.ok) {
      state.allProducts = await res.json();
      updateInventoryBadges();
      renderQuickCatalogGrid();
      populateTagStudioProducts();
    }
  } catch (err) {
    console.error('Failed to load products:', err);
  }
}

async function loadCategories() {
  try {
    const res = await fetch('/api/products/categories');
    if (res.ok) {
      state.categories = await res.json();
      populateCategoryDropdowns();
    }
  } catch (err) {
    console.error('Failed to load categories:', err);
  }
}

function updateInventoryBadges() {
  const lowCount = state.allProducts.filter(p => p.is_low_stock).length;
  const badge = document.getElementById('low-stock-badge');
  if (badge) {
    badge.textContent = lowCount;
    if (lowCount > 0) badge.classList.remove('hidden');
    else badge.classList.add('hidden');
  }
}

function renderPosCategoryChips() {
  const container = document.getElementById('pos-category-chips');
  if (!container) return;

  const cats = ['All', ...state.categories];
  container.innerHTML = '';
  cats.forEach(cat => {
    const btn = document.createElement('button');
    btn.className = (cat === state.activeCategory)
      ? 'px-3 py-1 rounded-full text-xs font-extrabold bg-white text-black whitespace-nowrap transition'
      : 'px-3 py-1 rounded-full text-xs font-semibold bg-zinc-950 text-zinc-400 hover:text-white border border-zinc-850 whitespace-nowrap transition';
    btn.textContent = cat;
    btn.onclick = () => {
      state.activeCategory = cat;
      renderPosCategoryChips();
      renderQuickCatalogGrid();
    };
    container.appendChild(btn);
  });
}

function toggleCatalogDrawer() {
  const drawer = document.getElementById('quick-catalog-grid');
  drawer.classList.toggle('hidden');
  if (!drawer.classList.contains('hidden')) {
    renderQuickCatalogGrid();
  }
}

function renderQuickCatalogGrid() {
  const grid = document.getElementById('quick-catalog-grid');
  if (!grid) return;

  const filtered = state.allProducts.filter(p => {
    if (state.activeCategory === 'All') return true;
    return p.category === state.activeCategory;
  });

  grid.innerHTML = '';
  filtered.forEach(p => {
    const card = document.createElement('div');
    card.className = 'bg-pitch hover:bg-zinc-900 p-2.5 rounded-xl border border-zinc-800 cursor-pointer flex flex-col justify-between transition hover:border-zinc-500 group shadow-sm';
    card.onclick = () => {
      addProductToCart(p);
      playBeep(987.77, 0.08);
    };

    card.innerHTML = `
      <div>
        ${p.image_url ? `
          <div class="relative w-full h-24 mb-2 rounded-lg overflow-hidden bg-black border border-zinc-850">
            <img src="${p.image_url}" alt="${escapeHtml(p.name)}" class="w-full h-full object-cover group-hover:scale-105 transition duration-300">
            <span class="absolute top-1.5 left-1.5 text-[9px] font-extrabold uppercase text-white bg-black/80 backdrop-blur-sm border border-zinc-700 px-1.5 py-0.5 rounded">${p.size || 'FS'}</span>
            <span class="absolute bottom-1.5 right-1.5 text-[9px] text-zinc-200 bg-black/80 px-1.5 py-0.5 rounded font-mono">${p.stock_quantity} left</span>
          </div>
        ` : `
          <div class="flex items-center justify-between mb-1.5">
            <span class="text-[9px] font-extrabold uppercase text-white bg-zinc-900 border border-zinc-800 px-1.5 py-0.2 rounded">${p.size || 'FS'}</span>
            <span class="text-[9px] text-zinc-400 font-mono">${p.stock_quantity} in stock</span>
          </div>
        `}
        <p class="text-xs font-bold text-white truncate">${escapeHtml(p.name)}</p>
        <p class="text-[10px] text-zinc-500 truncate">${p.color || ''} • ${p.category}</p>
      </div>
      <div class="mt-2 flex items-center justify-between border-t border-zinc-900 pt-1.5">
        <span class="text-xs font-extrabold text-emerald-400 font-mono">${state.settings.currency_symbol}${p.selling_price}</span>
        <span class="text-[10px] text-zinc-400 font-bold group-hover:text-white transition"><i class="fa-solid fa-plus"></i></span>
      </div>
    `;
    grid.appendChild(card);
  });
}

function populateCategoryDropdowns() {
  const invCatFilter = document.getElementById('inventory-cat-filter');
  if (invCatFilter) {
    invCatFilter.innerHTML = '<option value="All">All Categories</option>';
    state.categories.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c;
      opt.textContent = c;
      invCatFilter.appendChild(opt);
    });
  }
}

async function loadInventory() {
  const search = document.getElementById('inventory-search').value.trim();
  const cat = document.getElementById('inventory-cat-filter').value;
  const status = document.getElementById('inventory-status-filter').value;

  let url = `/api/products?1=1`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  if (cat && cat !== 'All') url += `&category=${encodeURIComponent(cat)}`;
  if (status === 'low') url += `&low_stock_only=true`;

  try {
    const res = await fetch(url);
    if (res.ok) {
      const products = await res.json();
      renderInventoryTable(products);
      calculateInventoryMetrics(products);
    }
  } catch (err) {
    console.error('Error loading inventory:', err);
  }
}

function calculateInventoryMetrics(products) {
  const totalStyles = products.length;
  const totalUnits = products.reduce((sum, p) => sum + p.stock_quantity, 0);
  const retailVal = products.reduce((sum, p) => sum + (p.stock_quantity * p.selling_price), 0);
  const costVal = products.reduce((sum, p) => sum + (p.stock_quantity * p.cost_price), 0);
  const lowCount = products.filter(p => p.is_low_stock).length;

  document.getElementById('inv-stat-products').textContent = totalStyles;
  document.getElementById('inv-stat-units').textContent = totalUnits;
  document.getElementById('inv-stat-retail').textContent = Math.round(retailVal).toLocaleString();
  document.getElementById('inv-stat-cost').textContent = Math.round(costVal).toLocaleString();
  document.getElementById('inv-stat-low').textContent = lowCount;
}

function renderInventoryTable(products) {
  const tbody = document.getElementById('inventory-table-body');
  tbody.innerHTML = '';

  products.forEach(p => {
    const tr = document.createElement('tr');
    tr.className = 'luxury-row text-xs border-b border-zinc-850 transition';

    let stockBadge = `<span class="px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-mono font-bold">${p.stock_quantity}</span>`;
    if (p.stock_quantity <= 0) {
      stockBadge = `<span class="px-2 py-0.5 rounded-full bg-red-500/15 border border-red-500/40 text-red-400 font-mono font-bold">0 (Out)</span>`;
    } else if (p.is_low_stock) {
      stockBadge = `<span class="px-2 py-0.5 rounded-full bg-red-500/20 border border-red-500/50 text-red-400 font-mono font-bold">${p.stock_quantity} (Low)</span>`;
    }

    tr.innerHTML = `
      <td class="py-2.5 px-3 text-center">
        ${p.image_url ? `
          <img src="${p.image_url}" alt="${escapeHtml(p.name)}" 
            class="w-10 h-10 object-cover rounded-xl border border-zinc-800 mx-auto cursor-pointer hover:scale-105 hover:border-zinc-500 transition shadow" 
            title="Click to view full photo"
            onclick="openImagePreviewModal('${p.image_url}', '${escapeHtml(p.name)}', '${p.sku} • Size: ${p.size} • ${state.settings.currency_symbol}${p.selling_price}')">
        ` : `
          <div class="w-10 h-10 rounded-xl bg-zinc-900 border border-zinc-850 mx-auto flex items-center justify-center text-zinc-600">
            <i class="fa-solid fa-shirt text-xs"></i>
          </div>
        `}
      </td>
      <td class="py-2.5 px-3 font-bold text-white">
        ${escapeHtml(p.name)}
        <div class="text-[10px] text-zinc-400 font-normal">${p.brand || 'SOL'}</div>
      </td>
      <td class="py-2.5 px-3 font-mono text-[11px] text-zinc-300">
        <div>${p.sku}</div>
        <div class="text-[10px] text-zinc-500">${p.barcode || ''}</div>
      </td>
      <td class="py-2.5 px-3 text-zinc-400">${p.category}</td>
      <td class="py-2.5 px-3 text-center">
        <span class="px-1.5 py-0.5 rounded bg-zinc-900 border border-zinc-800 font-bold text-white text-[10px]">${p.size}</span>
        <span class="text-zinc-400 text-[11px] ml-1">${p.color}</span>
      </td>
      <td class="py-2.5 px-3 text-right font-mono text-zinc-400">${state.settings.currency_symbol}${p.cost_price}</td>
      <td class="py-2.5 px-3 text-right font-mono font-bold text-emerald-400">${state.settings.currency_symbol}${p.selling_price}</td>
      <td class="py-2.5 px-3 text-center">${stockBadge}</td>
      <td class="py-2.5 px-4 text-center">
        <div class="inline-flex items-center gap-1.5">
          <button onclick="openRestockModal(${p.id}, '${escapeHtml(p.name)}')" class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 text-white text-[10px] font-bold transition" title="Quick Restock">
            +Stock
          </button>
          <button onclick="editProduct(${JSON.stringify(p).replace(/"/g, '&quot;')})" class="p-1 text-zinc-400 hover:text-white" title="Edit">
            <i class="fa-solid fa-pen-to-square"></i>
          </button>
          <button onclick="openTagStudioForProduct(${p.id})" class="p-1 text-zinc-400 hover:text-white" title="Customize & Print Tag">
            <i class="fa-solid fa-qrcode"></i>
          </button>
          <button onclick="deleteProduct(${p.id})" class="p-1 text-zinc-600 hover:text-white" title="Delete">
            <i class="fa-solid fa-trash"></i>
          </button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function openProductModal(prod = null) {
  document.getElementById('modal-product').classList.remove('hidden');
  if (prod) {
    document.getElementById('modal-product-title').textContent = 'Edit Style';
    document.getElementById('prod-edit-id').value = prod.id;
    document.getElementById('prod-name').value = prod.name;
    document.getElementById('prod-sku').value = prod.sku;
    document.getElementById('prod-barcode').value = prod.barcode || '';
    document.getElementById('prod-category').value = prod.category;
    document.getElementById('prod-size').value = prod.size;
    document.getElementById('prod-color').value = prod.color;
    document.getElementById('prod-brand').value = prod.brand || 'SOL';
    document.getElementById('prod-stock').value = prod.stock_quantity;
    document.getElementById('prod-cost').value = prod.cost_price;
    document.getElementById('prod-selling').value = prod.selling_price;
    document.getElementById('prod-low-limit').value = prod.low_stock_threshold;
    
    // Photo preview
    if (prod.image_url) {
      document.getElementById('prod-image-url').value = prod.image_url;
      document.getElementById('prod-manual-preview-img').src = prod.image_url;
      document.getElementById('prod-manual-preview-img').classList.remove('hidden');
      document.getElementById('prod-manual-placeholder-icon').classList.add('hidden');
      document.getElementById('prod-manual-clear-photo-btn').classList.remove('hidden');
    } else {
      clearManualProductPhoto();
    }
  } else {
    document.getElementById('modal-product-title').textContent = 'Add New Style';
    document.getElementById('prod-edit-id').value = '';
    document.getElementById('prod-name').value = '';
    document.getElementById('prod-sku').value = 'SOL-' + Math.floor(1000 + Math.random() * 9000);
    document.getElementById('prod-barcode').value = '890' + Math.floor(1000000 + Math.random() * 9000000);
    document.getElementById('prod-category').value = 'Shirts';
    document.getElementById('prod-size').value = 'M';
    document.getElementById('prod-color').value = 'Jet Black';
    document.getElementById('prod-brand').value = 'SOL';
    document.getElementById('prod-stock').value = '10';
    document.getElementById('prod-cost').value = '600';
    document.getElementById('prod-selling').value = '1499';
    document.getElementById('prod-low-limit').value = '5';
    clearManualProductPhoto();
  }
}

function handleManualProductPhoto(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async (e) => {
    const dataUrl = e.target.result;
    document.getElementById('prod-manual-preview-img').src = dataUrl;
    document.getElementById('prod-manual-preview-img').classList.remove('hidden');
    document.getElementById('prod-manual-placeholder-icon').classList.add('hidden');
    document.getElementById('prod-manual-clear-photo-btn').classList.remove('hidden');

    try {
      const res = await fetch('/api/products/upload-and-analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_data: dataUrl, filename: file.name || 'manual.jpg' })
      });
      if (res.ok) {
        const data = await res.json();
        document.getElementById('prod-image-url').value = data.image_url;
      }
    } catch (err) {
      console.error('Failed to upload manual photo:', err);
    }
  };
  reader.readAsDataURL(file);
}

function clearManualProductPhoto() {
  document.getElementById('prod-image-url').value = '';
  document.getElementById('prod-manual-file-input').value = '';
  document.getElementById('prod-manual-preview-img').src = '';
  document.getElementById('prod-manual-preview-img').classList.add('hidden');
  document.getElementById('prod-manual-placeholder-icon').classList.remove('hidden');
  document.getElementById('prod-manual-clear-photo-btn').classList.add('hidden');
}

function editProduct(prod) {
  openProductModal(prod);
}

function closeProductModal() {
  document.getElementById('modal-product').classList.add('hidden');
}

async function saveProduct() {
  const editId = document.getElementById('prod-edit-id').value;
  const payload = {
    name: document.getElementById('prod-name').value.trim(),
    sku: document.getElementById('prod-sku').value.trim(),
    barcode: document.getElementById('prod-barcode').value.trim(),
    category: document.getElementById('prod-category').value.trim() || 'General',
    size: document.getElementById('prod-size').value.trim() || 'Free Size',
    color: document.getElementById('prod-color').value.trim() || 'Standard',
    brand: document.getElementById('prod-brand').value.trim() || 'SOL',
    stock_quantity: parseInt(document.getElementById('prod-stock').value) || 0,
    cost_price: parseFloat(document.getElementById('prod-cost').value) || 0,
    selling_price: parseFloat(document.getElementById('prod-selling').value) || 0,
    low_stock_threshold: parseInt(document.getElementById('prod-low-limit').value) || 5,
    image_url: document.getElementById('prod-image-url').value.trim() || null
  };

  if (!payload.name || !payload.sku || payload.selling_price <= 0) {
    alert('Please enter product name, SKU, and a valid selling price.');
    return;
  }

  try {
    const url = editId ? `/api/products/${editId}` : `/api/products`;
    const method = editId ? 'PUT' : 'POST';

    const res = await fetch(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      closeProductModal();
      await loadProducts();
      await loadCategories();
      renderPosCategoryChips();
      loadInventory();
    } else {
      const err = await res.json();
      alert('Error saving style: ' + (err.detail || 'Failed'));
    }
  } catch (err) {
    alert('Request failed: ' + err.message);
  }
}

// ==============================================================
// 15. SMART PHOTO STOCK INTAKE & VISUAL ORGANIZER
// ==============================================================

state.intakeSelectedSize = 'M';
state.intakeBaseSku = '';

function openSmartPhotoIntakeModal() {
  state.intakeSelectedSize = 'M';
  state.intakeBaseSku = 'SOL-' + Math.floor(1000 + Math.random() * 9000);
  
  // Reset form fields
  document.getElementById('intake-image-url').value = '';
  document.getElementById('intake-name').value = '';
  document.getElementById('intake-category').value = 'T-Shirts';
  document.getElementById('intake-color').value = '';
  document.getElementById('intake-custom-size').value = '';
  document.getElementById('intake-selling-price').value = '1499';
  document.getElementById('intake-cost-price').value = '600';
  document.getElementById('intake-stock').value = '10';
  document.getElementById('intake-sku').value = `${state.intakeBaseSku}-M`;
  document.getElementById('intake-barcode').value = '890' + Math.floor(1000000 + Math.random() * 9000000);

  // Reset visual cards
  document.getElementById('photo-intake-preview-img').src = '';
  document.getElementById('photo-intake-preview-container').classList.add('hidden');
  document.getElementById('photo-intake-empty-state').classList.remove('hidden');
  document.getElementById('photo-intake-loading-badge').classList.add('hidden');
  document.getElementById('photo-intake-success-badge').classList.add('hidden');

  // Highlight 'M' pill by default
  selectIntakeSize('M');

  document.getElementById('modal-photo-intake').classList.remove('hidden');
}

function closeSmartPhotoIntakeModal() {
  document.getElementById('modal-photo-intake').classList.add('hidden');
}

function triggerIntakeCamera() {
  const cam = document.getElementById('photo-intake-camera');
  if (cam) cam.click();
}

function triggerIntakeFile() {
  const file = document.getElementById('photo-intake-file');
  if (file) file.click();
}

async function handlePhotoIntakeFile(file) {
  if (!file) return;

  const reader = new FileReader();
  reader.onload = async (e) => {
    const dataUrl = e.target.result;
    
    // Show image immediately in preview
    document.getElementById('photo-intake-preview-img').src = dataUrl;
    document.getElementById('photo-intake-empty-state').classList.add('hidden');
    document.getElementById('photo-intake-preview-container').classList.remove('hidden');
    document.getElementById('photo-intake-loading-badge').classList.remove('hidden');
    document.getElementById('photo-intake-success-badge').classList.add('hidden');

    try {
      const res = await fetch('/api/products/upload-and-analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_data: dataUrl,
          filename: file.name || 'garment.jpg'
        })
      });

      if (res.ok) {
        const data = await res.json();
        
        // Hide loading, show success badge
        document.getElementById('photo-intake-loading-badge').classList.add('hidden');
        document.getElementById('photo-intake-success-badge').classList.remove('hidden');
        document.getElementById('photo-intake-ai-tag').textContent = `Recognized: ${data.category} (${data.color})`;

        // Populate fields
        document.getElementById('intake-image-url').value = data.image_url;
        document.getElementById('intake-name').value = data.detected_name || 'SOL Garment Essential';
        
        // Set category if present in options
        const catSelect = document.getElementById('intake-category');
        if (data.category) {
          let found = false;
          for (let i = 0; i < catSelect.options.length; i++) {
            if (catSelect.options[i].value.toLowerCase().includes(data.category.toLowerCase()) || 
                data.category.toLowerCase().includes(catSelect.options[i].value.toLowerCase())) {
              catSelect.selectedIndex = i;
              found = true;
              break;
            }
          }
          if (!found) {
            const opt = document.createElement('option');
            opt.value = data.category;
            opt.textContent = data.category;
            opt.selected = true;
            catSelect.appendChild(opt);
          }
        }

        // Set color
        if (data.color) {
          document.getElementById('intake-color').value = data.color;
        }

        // Set prices
        if (data.suggested_selling_price) {
          document.getElementById('intake-selling-price').value = data.suggested_selling_price;
        }
        if (data.suggested_cost_price) {
          document.getElementById('intake-cost-price').value = data.suggested_cost_price;
        }

        // Set base SKU
        state.intakeBaseSku = data.sku_suggestion || ('SOL-' + Math.floor(1000 + Math.random() * 9000));
        document.getElementById('intake-sku').value = `${state.intakeBaseSku}-${state.intakeSelectedSize}`;
        
        if (data.barcode_suggestion) {
          document.getElementById('intake-barcode').value = data.barcode_suggestion;
        }

        // If suggestions include sizes, select first
        if (data.suggested_sizes && data.suggested_sizes.length > 0) {
          selectIntakeSize(data.suggested_sizes[0]);
        }

        playSuccessChime();
      } else {
        document.getElementById('photo-intake-loading-badge').classList.add('hidden');
      }
    } catch (err) {
      console.error('Photo analysis error:', err);
      document.getElementById('photo-intake-loading-badge').classList.add('hidden');
    }
  };

  reader.readAsDataURL(file);
}

function selectIntakeSize(size) {
  state.intakeSelectedSize = size;
  document.getElementById('intake-active-size-label').textContent = size;

  // Highlight matching pill
  const pills = document.querySelectorAll('.size-pill-btn');
  pills.forEach(btn => {
    if (btn.textContent.trim() === size) {
      btn.className = 'size-pill-btn px-2.5 py-1 rounded-lg border border-white bg-white text-black text-xs font-extrabold hover:bg-zinc-200 transition';
    } else {
      btn.className = 'size-pill-btn px-2.5 py-1 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-300 text-xs font-bold hover:border-zinc-500 transition';
    }
  });

  updateIntakeSku();
}

function handleCustomSizeInput(val) {
  const trimmed = val.trim();
  if (trimmed) {
    state.intakeSelectedSize = trimmed;
    document.getElementById('intake-active-size-label').textContent = trimmed;
    // Unhighlight standard pills
    document.querySelectorAll('.size-pill-btn').forEach(btn => {
      btn.className = 'size-pill-btn px-2.5 py-1 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-300 text-xs font-bold hover:border-zinc-500 transition';
    });
    updateIntakeSku();
  }
}

function updateIntakeSku() {
  if (!state.intakeBaseSku) {
    state.intakeBaseSku = 'SOL-' + Math.floor(1000 + Math.random() * 9000);
  }
  const sizeCode = (state.intakeSelectedSize || 'FS').replace(/\s+/g, '');
  document.getElementById('intake-sku').value = `${state.intakeBaseSku}-${sizeCode}`;
}

async function savePhotoIntakeProduct(addAnotherSize = false) {
  const name = document.getElementById('intake-name').value.trim();
  const category = document.getElementById('intake-category').value.trim() || 'General';
  const color = document.getElementById('intake-color').value.trim() || 'Standard';
  const size = state.intakeSelectedSize || 'Free Size';
  const sku = document.getElementById('intake-sku').value.trim();
  const barcode = document.getElementById('intake-barcode').value.trim();
  const selling_price = parseFloat(document.getElementById('intake-selling-price').value) || 0;
  const cost_price = parseFloat(document.getElementById('intake-cost-price').value) || 0;
  const stock_quantity = parseInt(document.getElementById('intake-stock').value) || 0;
  const image_url = document.getElementById('intake-image-url').value.trim() || null;

  if (!name) {
    alert('Please enter a garment title or snap/upload a photo.');
    return;
  }
  if (!sku) {
    alert('Please enter or generate a SKU.');
    return;
  }
  if (selling_price <= 0) {
    alert('Please enter a valid selling price (MRP).');
    return;
  }

  const payload = {
    name,
    sku,
    barcode,
    category,
    size,
    color,
    brand: 'SOL',
    stock_quantity,
    cost_price,
    selling_price,
    low_stock_threshold: 5,
    image_url
  };

  try {
    const res = await fetch('/api/products', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      playBeep(987.77, 0.12);
      await loadProducts();
      await loadCategories();
      renderPosCategoryChips();
      loadInventory();

      if (addAnotherSize) {
        // Transition to next size logically
        const sizeOrder = ['XS', 'S', 'M', 'L', 'XL', 'XXL', '28', '30', '32', '34', '36', '38'];
        const currentIdx = sizeOrder.indexOf(size);
        const nextSize = (currentIdx !== -1 && currentIdx < sizeOrder.length - 1) ? sizeOrder[currentIdx + 1] : 'L';
        
        selectIntakeSize(nextSize);
        // Refresh barcode for new size
        document.getElementById('intake-barcode').value = '890' + Math.floor(1000000 + Math.random() * 9000000);
        
        // Brief alert / confirmation
        alert(`Saved ${size} (${sku}) to inventory! Now enter stock & details for size ${nextSize}.`);
      } else {
        closeSmartPhotoIntakeModal();
      }
    } else {
      const err = await res.json();
      alert('Error saving garment: ' + (err.detail || 'Could not save to stock'));
    }
  } catch (err) {
    alert('Failed to save garment: ' + err.message);
  }
}

// Full-Res Image Lightbox Modal
function openImagePreviewModal(url, title = 'Garment Photo', subtitle = '') {
  document.getElementById('preview-modal-img').src = url;
  document.getElementById('preview-image-title').textContent = title;
  document.getElementById('preview-image-subtitle').textContent = subtitle || 'SOL • Soul of Lifestyle';
  document.getElementById('modal-image-preview').classList.remove('hidden');
}

function closeImagePreviewModal() {
  document.getElementById('modal-image-preview').classList.add('hidden');
}

async function deleteProduct(id) {
  if (confirm('Delete this style from inventory?')) {
    try {
      const res = await fetch(`/api/products/${id}`, { method: 'DELETE' });
      if (res.ok) {
        await loadProducts();
        loadInventory();
      }
    } catch (e) {
      alert(e.message);
    }
  }
}

function openRestockModal(id, title) {
  document.getElementById('restock-prod-id').value = id;
  document.getElementById('restock-prod-title').textContent = title;
  document.getElementById('restock-qty').value = '10';
  document.getElementById('restock-note').value = 'New production shipment';
  document.getElementById('modal-restock').classList.remove('hidden');
}

function closeRestockModal() {
  document.getElementById('modal-restock').classList.add('hidden');
}

async function submitStockAdjustment() {
  const prodId = document.getElementById('restock-prod-id').value;
  const qty = parseInt(document.getElementById('restock-qty').value) || 0;
  const note = document.getElementById('restock-note').value.trim();

  if (qty <= 0) {
    alert('Please specify a positive quantity to restock.');
    return;
  }

  try {
    const res = await fetch(`/api/products/${prodId}/adjust-stock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        quantity_change: qty,
        reason: 'restock',
        note: note
      })
    });
    if (res.ok) {
      closeRestockModal();
      playBeep(800, 0.08);
      await loadProducts();
      loadInventory();
    }
  } catch (err) {
    alert('Restock failed: ' + err.message);
  }
}

// ==============================================================
// 11. CUSTOMER CRM
// ==============================================================

async function loadCRM() {
  const search = document.getElementById('crm-search-input').value.trim();
  const url = search ? `/api/customers?search=${encodeURIComponent(search)}` : `/api/customers`;

  try {
    const res = await fetch(url);
    if (res.ok) {
      const customers = await res.json();
      renderCustomerCards(customers);
    }
  } catch (err) {
    console.error('Error loading CRM:', err);
  }
}

function renderCustomerCards(customers) {
  const grid = document.getElementById('crm-customers-grid');
  grid.innerHTML = '';

  customers.forEach(c => {
    const card = document.createElement('div');
    card.className = 'bg-card p-4 rounded-2xl border border-zinc-850 shadow flex flex-col justify-between hover:border-zinc-700 transition';

    card.innerHTML = `
      <div>
        <div class="flex items-start justify-between">
          <div>
            <h4 class="font-extrabold text-sm text-white">${escapeHtml(c.name)}</h4>
            <p class="font-mono text-xs text-zinc-400 mt-0.5">${c.phone}</p>
          </div>
          <span class="text-[9px] font-extrabold uppercase px-2 py-0.5 rounded ${c.tier === 'VIP' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'bg-white text-black'} font-mono">
            ${c.tier}
          </span>
        </div>

        <div class="grid grid-cols-2 gap-2 my-3 text-xs bg-pitch p-2.5 rounded-xl border border-zinc-850">
          <div>
            <span class="text-[9px] text-zinc-500 uppercase block">Total Spent</span>
            <span class="font-mono font-bold text-emerald-400">${state.settings.currency_symbol}${c.total_spent.toLocaleString()}</span>
          </div>
          <div>
            <span class="text-[9px] text-zinc-500 uppercase block">Orders</span>
            <span class="font-mono font-bold text-white">${c.total_orders} visits</span>
          </div>
          <div class="col-span-2 text-[11px] text-zinc-400">
            ${c.city ? `<span><i class="fa-solid fa-location-dot mr-1 text-zinc-600"></i>${escapeHtml(c.city)}</span>` : ''}
            ${c.email ? `<span class="ml-2 truncate"><i class="fa-solid fa-envelope mr-1 text-zinc-600"></i>${escapeHtml(c.email)}</span>` : ''}
          </div>
        </div>

        ${c.notes ? `<p class="text-[11px] text-zinc-400 italic bg-black p-2 rounded-lg border border-zinc-900 mb-3 truncate">"${escapeHtml(c.notes)}"</p>` : ''}
      </div>

      <div class="flex items-center gap-2 pt-2 border-t border-zinc-850">
        <button onclick="viewCustomerHistory(${c.id})" class="flex-1 py-1.5 rounded-xl bg-zinc-900 hover:bg-zinc-800 text-white text-xs font-bold transition border border-zinc-800">
          <i class="fa-solid fa-clock-rotate-left mr-1"></i> History
        </button>
        <button onclick="startBillForCustomer(${JSON.stringify(c).replace(/"/g, '&quot;')})" class="flex-1 py-1.5 rounded-xl bg-white hover:bg-zinc-200 text-black text-xs font-bold transition shadow">
          <i class="fa-solid fa-cash-register mr-1"></i> Bill
        </button>
        <a href="https://wa.me/${c.phone.replace(/[^0-9]/g, '')}" target="_blank" class="p-2 rounded-xl bg-zinc-900 hover:bg-zinc-800 text-white text-xs border border-zinc-800 transition" title="WhatsApp Customer">
          <i class="fa-brands fa-whatsapp text-sm"></i>
        </a>
      </div>
    `;
    grid.appendChild(card);
  });
}

function startBillForCustomer(cust) {
  switchTab('billing');
  selectCustomer(cust);
}

async function viewCustomerHistory(custId) {
  try {
    const res = await fetch(`/api/customers/${custId}`);
    if (res.ok) {
      const data = await res.json();
      document.getElementById('history-cust-name').textContent = data.name;
      document.getElementById('history-cust-phone').textContent = data.phone;
      document.getElementById('history-total-spent').textContent = data.total_spent.toLocaleString();
      document.getElementById('history-tier').textContent = data.tier;
      document.getElementById('history-orders').textContent = data.total_orders;

      const listContainer = document.getElementById('history-invoices-list');
      listContainer.innerHTML = '';

      if (!data.purchase_history || data.purchase_history.length === 0) {
        listContainer.innerHTML = `<p class="text-center text-xs text-zinc-500 py-6">No previous orders recorded.</p>`;
      } else {
        data.purchase_history.forEach(inv => {
          const invCard = document.createElement('div');
          invCard.className = 'bg-pitch p-3 rounded-xl border border-zinc-800 text-xs';
          
          let itemsText = inv.items.map(it => `${it.product_name} (${it.size || ''}/${it.color || ''}) x${it.quantity}`).join(', ');

          invCard.innerHTML = `
            <div class="flex items-center justify-between font-bold">
              <span class="font-mono text-white">${inv.invoice_number}</span>
              <span class="font-mono text-white">${state.settings.currency_symbol}${inv.grand_total.toFixed(2)}</span>
            </div>
            <div class="text-[10px] text-zinc-400 mt-1 flex justify-between">
              <span>${new Date(inv.created_at).toLocaleDateString([], { dateStyle: 'medium', timeStyle: 'short' })}</span>
              <span>Paid via ${inv.payment_method}</span>
            </div>
            <p class="text-[11px] text-zinc-300 mt-1.5 border-t border-zinc-900 pt-1">
              <strong>Items:</strong> ${escapeHtml(itemsText)}
            </p>
          `;
          listContainer.appendChild(invCard);
        });
      }

      document.getElementById('modal-customer-history').classList.remove('hidden');
    }
  } catch (err) {
    alert('Failed to load history: ' + err.message);
  }
}

function closeCustomerHistoryModal() {
  document.getElementById('modal-customer-history').classList.add('hidden');
}

function openNewCustomerModal(initialPhoneOrName = '') {
  document.getElementById('cust-modal-name').value = '';
  document.getElementById('cust-modal-phone').value = '';
  document.getElementById('cust-modal-email').value = '';
  document.getElementById('cust-modal-city').value = '';
  document.getElementById('cust-modal-notes').value = '';

  if (initialPhoneOrName) {
    if (/^\+?[0-9\s-]{6,15}$/.test(initialPhoneOrName)) {
      document.getElementById('cust-modal-phone').value = initialPhoneOrName;
    } else {
      document.getElementById('cust-modal-name').value = initialPhoneOrName;
    }
  }

  document.getElementById('modal-customer').classList.remove('hidden');
}

function closeNewCustomerModal() {
  document.getElementById('modal-customer').classList.add('hidden');
}

async function saveNewCustomer() {
  const name = document.getElementById('cust-modal-name').value.trim();
  const phone = document.getElementById('cust-modal-phone').value.trim();
  const email = document.getElementById('cust-modal-email').value.trim();
  const city = document.getElementById('cust-modal-city').value.trim();
  const notes = document.getElementById('cust-modal-notes').value.trim();

  if (!name || !phone) {
    alert('Please enter both Customer Name and Phone Number.');
    return;
  }

  try {
    const res = await fetch('/api/customers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, phone, email, city, notes })
    });

    if (res.ok) {
      const created = await res.json();
      closeNewCustomerModal();
      await loadCustomers();
      loadCRM();
      selectCustomer(created);
    } else {
      const err = await res.json();
      alert('Error creating customer: ' + (err.detail || 'Failed'));
    }
  } catch (err) {
    alert('Request error: ' + err.message);
  }
}

// ==============================================================
// 12. ANALYTICS & BEST-SELLERS LEADERBOARD
// ==============================================================

async function loadAnalytics() {
  try {
    const res = await fetch('/api/analytics/dashboard');
    if (res.ok) {
      const data = await res.json();
      renderAnalyticsDashboard(data);
    }
  } catch (err) {
    console.error('Failed to load analytics:', err);
  }
  loadRecentInvoices();
}

function renderAnalyticsDashboard(data) {
  const k = data.kpi;
  document.getElementById('ana-today-rev').textContent = k.today_revenue.toLocaleString();
  document.getElementById('ana-today-orders').textContent = k.today_orders;
  document.getElementById('ana-total-rev').textContent = k.total_revenue.toLocaleString();
  document.getElementById('ana-total-orders').textContent = k.total_orders;
  document.getElementById('ana-gross-profit').textContent = k.gross_profit.toLocaleString();
  document.getElementById('ana-total-customers').textContent = k.total_customers;

  // Best Selling Products Leaderboard
  const bestTbody = document.getElementById('best-sellers-table-body');
  bestTbody.innerHTML = '';

  if (data.best_selling_products.length === 0) {
    bestTbody.innerHTML = `<tr><td colspan="5" class="py-6 text-center text-zinc-500">No sales recorded yet.</td></tr>`;
  } else {
    data.best_selling_products.forEach((prod, index) => {
      const tr = document.createElement('tr');
      tr.className = 'luxury-row text-xs border-b border-zinc-850 transition';

      let rankBadge = `<span class="w-5 h-5 rounded bg-zinc-900 border border-zinc-800 text-white font-mono text-[10px] flex items-center justify-center font-bold">#${index + 1}</span>`;
      if (index === 0) rankBadge = `<span class="w-5 h-5 rounded bg-white text-black font-mono text-[10px] flex items-center justify-center font-extrabold">#1</span>`;

      tr.innerHTML = `
        <td class="py-3 px-3">
          <div class="flex items-center gap-2.5">
            ${rankBadge}
            <div>
              <span class="font-extrabold text-white text-xs">${escapeHtml(prod.product_name)}</span>
              <div class="text-[10px] text-zinc-500 font-mono">${prod.sku} ${prod.size ? '• ' + prod.size : ''} ${prod.color ? '• ' + prod.color : ''}</div>
            </div>
          </div>
        </td>
        <td class="py-3 px-3 text-zinc-400">${prod.category || 'General'}</td>
        <td class="py-3 px-3 text-center">
          <span class="font-mono font-bold text-white text-xs bg-zinc-900 border border-zinc-800 px-2 py-0.5 rounded">
            ${prod.units_sold} sold
          </span>
        </td>
        <td class="py-3 px-3 text-right font-mono font-extrabold text-emerald-400 text-xs">
          ${state.settings.currency_symbol}${prod.total_revenue_generated.toLocaleString()}
        </td>
        <td class="py-3 px-3 text-center font-mono">
          <span class="px-2 py-0.5 rounded text-zinc-300">
            ${prod.current_stock ?? 'N/A'} left
          </span>
        </td>
      `;
      bestTbody.appendChild(tr);
    });
  }

  // Category Breakdown
  const catContainer = document.getElementById('category-share-list');
  catContainer.innerHTML = '';
  const totalCatSales = data.category_breakdown.reduce((sum, c) => sum + c.total_sales, 0);

  data.category_breakdown.forEach(cat => {
    const pct = totalCatSales > 0 ? Math.round((cat.total_sales / totalCatSales) * 100) : 0;
    const catRow = document.createElement('div');
    catRow.className = 'text-xs space-y-1';
    catRow.innerHTML = `
      <div class="flex justify-between font-semibold">
        <span class="text-zinc-300">${escapeHtml(cat.category)}</span>
        <span class="font-mono text-emerald-400 font-bold">${state.settings.currency_symbol}${cat.total_sales.toLocaleString()} (${pct}%)</span>
      </div>
      <div class="w-full bg-black rounded-full h-1.5 overflow-hidden border border-zinc-900">
        <div class="bg-white h-1.5 rounded-full" style="width: ${pct}%"></div>
      </div>
    `;
    catContainer.appendChild(catRow);
  });

  // Low Stock Watchlist
  const lowContainer = document.getElementById('low-stock-radar-list');
  lowContainer.innerHTML = '';
  if (data.low_stock_alerts.length === 0) {
    lowContainer.innerHTML = `<p class="text-zinc-500 italic">All styles have healthy inventory levels.</p>`;
  } else {
    data.low_stock_alerts.slice(0, 4).forEach(prod => {
      const item = document.createElement('div');
      item.className = 'flex items-center justify-between bg-pitch p-2 rounded-xl border border-zinc-800';
      item.innerHTML = `
        <div>
          <span class="font-bold text-white truncate block max-w-[150px]">${escapeHtml(prod.name)}</span>
          <span class="text-[10px] text-zinc-500 font-mono">${prod.size} • ${prod.color}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="font-mono font-bold text-red-400 text-xs">${prod.stock_quantity} left</span>
          <button onclick="openRestockModal(${prod.id}, '${escapeHtml(prod.name)}')" class="px-2 py-0.5 rounded bg-white text-black text-[10px] font-bold transition">
            +Restock
          </button>
        </div>
      `;
      lowContainer.appendChild(item);
    });
  }
}

async function loadRecentInvoices() {
  try {
    const res = await fetch('/api/invoices?limit=15');
    if (res.ok) {
      const invoices = await res.json();
      const tbody = document.getElementById('recent-invoices-body');
      tbody.innerHTML = '';

      invoices.forEach(inv => {
        const tr = document.createElement('tr');
        tr.className = 'luxury-row text-xs border-b border-zinc-850 transition';

        tr.innerHTML = `
          <td class="py-2.5 px-3 font-mono font-bold text-white">${inv.invoice_number}</td>
          <td class="py-2.5 px-3 text-zinc-400">${new Date(inv.created_at).toLocaleDateString([], { dateStyle: 'short', timeStyle: 'short' })}</td>
          <td class="py-2.5 px-3">
            <span class="font-bold text-white">${escapeHtml(inv.customer_name)}</span>
            ${inv.customer_phone ? `<span class="text-[10px] text-zinc-500 font-mono block">${inv.customer_phone}</span>` : ''}
          </td>
          <td class="py-2.5 px-3 text-center font-mono text-zinc-400">${inv.total_qty || inv.item_count} items</td>
          <td class="py-2.5 px-3"><span class="px-2 py-0.5 rounded bg-zinc-900 border border-zinc-800 font-mono text-[10px] text-white">${inv.payment_method}</span></td>
          <td class="py-2.5 px-3 text-right font-mono font-bold text-emerald-400">${state.settings.currency_symbol}${inv.grand_total.toFixed(2)}</td>
          <td class="py-2.5 px-3 text-center">
            <button onclick="reprintInvoice(${inv.id})" class="px-2.5 py-1 rounded-lg bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 text-white text-xs font-semibold transition" title="View / Print">
              <i class="fa-solid fa-receipt mr-1"></i> Bill
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.error('Failed to load recent invoices:', err);
  }
}

async function reprintInvoice(id) {
  try {
    const res = await fetch(`/api/invoices/${id}`);
    if (res.ok) {
      const inv = await res.json();
      state.lastCompletedInvoice = inv;
      openInvoiceSuccessModal(inv);
    }
  } catch (err) {
    alert(err.message);
  }
}

// ==============================================================
// 13. GARMENT QR & BARCODE TAG STUDIO & GENERATOR
// ==============================================================

state.tagStudio = {
  selectedSize: 'M',
  activeView: 'all', // 'all' or 'queue'
  customQueue: [],
  selectedProductId: ''
};

function initTagStudio() {
  populateTagStudioProducts();
  updateLiveTagPreview();
}

function populateTagStudioProducts() {
  const sel = document.getElementById('tag-studio-select-product');
  if (!sel) return;

  const currentVal = sel.value;
  sel.innerHTML = '<option value="">-- Or Create / Customize Tag From Scratch --</option>';

  state.allProducts.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = `${p.name} (${p.size || 'FS'}/${p.color || '-'}) — ${state.settings.currency_symbol}${p.selling_price} [${p.sku}]`;
    sel.appendChild(opt);
  });

  if (currentVal) sel.value = currentVal;
}

function loadProductIntoTagStudio(productId) {
  state.tagStudio.selectedProductId = productId;
  if (!productId) {
    resetTagStudioToBlank();
    return;
  }

  const p = state.allProducts.find(x => x.id == productId);
  if (!p) return;

  document.getElementById('tag-studio-name').value = p.name;
  document.getElementById('tag-studio-price').value = p.selling_price;
  document.getElementById('tag-studio-category').value = p.category || 'T-Shirts';
  document.getElementById('tag-studio-color').value = p.color || 'Standard';
  document.getElementById('tag-studio-sku').value = p.sku;
  selectTagStudioSize(p.size || 'M');
}

function resetTagStudioToBlank() {
  const sel = document.getElementById('tag-studio-select-product');
  if (sel) sel.value = '';
  state.tagStudio.selectedProductId = '';
  document.getElementById('tag-studio-name').value = 'SOL Signature Heavyweight Tee';
  document.getElementById('tag-studio-category').value = 'T-Shirts';
  document.getElementById('tag-studio-price').value = '1499';
  document.getElementById('tag-studio-color').value = 'Jet Black';
  document.getElementById('tag-studio-copies').value = '1';
  document.getElementById('tag-studio-custom-size').value = '';
  generateNewTagSku();
  selectTagStudioSize('M');
}

function selectTagStudioSize(size) {
  state.tagStudio.selectedSize = size;
  const label = document.getElementById('tag-studio-active-size-label');
  if (label) label.textContent = size;

  // Highlight active pill
  document.querySelectorAll('.tag-size-pill').forEach(btn => {
    if (btn.textContent.trim() === size) {
      btn.className = 'tag-size-pill px-2.5 py-1 rounded-lg border border-white bg-white text-black text-xs font-extrabold hover:bg-zinc-200 transition';
    } else {
      btn.className = 'tag-size-pill px-2.5 py-1 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-300 text-xs font-bold hover:border-zinc-500 transition';
    }
  });

  updateTagStudioSkuForSize(size);
  updateLiveTagPreview();
}

function handleTagStudioCustomSize(val) {
  const trimmed = val.trim();
  if (trimmed) {
    state.tagStudio.selectedSize = trimmed;
    const label = document.getElementById('tag-studio-active-size-label');
    if (label) label.textContent = trimmed;

    // Unhighlight standard pills
    document.querySelectorAll('.tag-size-pill').forEach(btn => {
      btn.className = 'tag-size-pill px-2.5 py-1 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-300 text-xs font-bold hover:border-zinc-500 transition';
    });

    updateTagStudioSkuForSize(trimmed);
    updateLiveTagPreview();
  }
}

function updateTagStudioSkuForSize(size) {
  const input = document.getElementById('tag-studio-sku');
  if (!input) return;
  let current = input.value.trim();
  if (!current) {
    input.value = `SOL-ITEM-${Math.floor(1000 + Math.random() * 9000)}-${size}`;
    return;
  }
  // Replace trailing -SIZE if already present
  const sizePattern = /-(XS|S|M|L|XL|XXL|3XL|28|30|32|34|36|38|FS)$/i;
  if (sizePattern.test(current)) {
    input.value = current.replace(sizePattern, `-${size}`);
  }
}

function generateNewTagSku() {
  const cat = document.getElementById('tag-studio-category').value.trim() || 'TS';
  const prefix = cat.substring(0, 3).toUpperCase().replace(/[^A-Z]/g, '') || 'SOL';
  const size = state.tagStudio.selectedSize || 'M';
  const rand = Math.floor(1000 + Math.random() * 9000);
  const newSku = `SOL-${prefix}-${rand}-${size}`;
  document.getElementById('tag-studio-sku').value = newSku;
  updateLiveTagPreview();
}

function updateLiveTagPreview() {
  const container = document.getElementById('live-tag-preview-wrapper');
  if (!container) return;

  const name = document.getElementById('tag-studio-name').value.trim() || 'SOL Signature Piece';
  const price = parseFloat(document.getElementById('tag-studio-price').value) || 0;
  const category = document.getElementById('tag-studio-category').value.trim() || 'Apparel';
  const color = document.getElementById('tag-studio-color').value.trim() || 'Standard';
  const size = state.tagStudio.selectedSize || 'M';
  const sku = document.getElementById('tag-studio-sku').value.trim() || 'SOL-001';
  const format = document.getElementById('tag-studio-format').value || 'hangtag';

  container.innerHTML = '';

  const tagDom = createTagCardElement({
    name,
    price,
    category,
    color,
    size,
    sku,
    format
  }, 'preview-tag');

  container.appendChild(tagDom);
}

function createTagCardElement(item, uniqueId) {
  const s = state.settings;
  const format = item.format || 'hangtag';

  const card = document.createElement('div');

  if (format === 'sticker') {
    card.className = 'sticker-tag';
    card.innerHTML = `
      <div style="text-align: center; width: 100%;">
        <span style="font-size: 8.5px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase;">SOL • SOUL OF LIFESTYLE</span>
        <h4 style="font-size: 11px; font-weight: 800; color: #000; margin: 2px 0 0 0; line-height: 1.2; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
          ${escapeHtml(item.name)}
        </h4>
        <div style="font-size: 9px; font-weight: 700; color: #333; margin-top: 1px;">
          SIZE: <strong>${escapeHtml(item.size)}</strong> | COLOR: <strong>${escapeHtml(item.color)}</strong>
        </div>
      </div>

      <div style="margin: 4px 0; text-align: center; width: 100%;">
        <svg id="${uniqueId}-barcode" style="max-width: 100%; height: 38px; margin: 0 auto; display: block;"></svg>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: baseline; width: 100%; border-top: 1px dashed #000; padding-top: 3px;">
        <span style="font-size: 8px; font-mono font-bold;">M.R.P. (INCL. TAX)</span>
        <span style="font-size: 14.5px; font-weight: 900; font-family: monospace;">${s.currency_symbol}${Number(item.price).toFixed(0)}</span>
      </div>
    `;

    setTimeout(() => {
      const svgEl = document.getElementById(`${uniqueId}-barcode`);
      if (svgEl && window.JsBarcode) {
        try {
          JsBarcode(svgEl, item.sku || 'SOL-001', {
            format: "CODE128",
            width: 1.2,
            height: 30,
            displayValue: true,
            fontSize: 8.5,
            margin: 2,
            textMargin: 1
          });
        } catch (e) {
          console.warn('JsBarcode note:', e);
        }
      }
    }, 30);

    return card;
  }

  // Default Luxury Hang Tag (or Dual)
  card.className = 'garment-tag';
  card.innerHTML = `
    <div style="text-align: center; width: 100%;">
      <img src="/static/sol_logo_black.svg" alt="SOL" style="max-height: 34px; width: auto; margin: 0 auto 6px auto; display: block;">
      <h4 style="font-size: 12px; font-weight: 800; color: #000; margin: 4px 0 1px 0; line-height: 1.2; max-height: 28px; overflow: hidden;">
        ${escapeHtml(item.name)}
      </h4>
      <span style="font-size: 9px; color: #555; text-transform: uppercase; letter-spacing: 0.5px;">${escapeHtml(item.category || 'Luxury Wear')}</span>
    </div>

    <div style="margin: 6px 0; padding: 4px; background: white; border: 1px solid #000; border-radius: 4px; display: flex; justify-content: center; align-items: center;">
      <div id="${uniqueId}-qr"></div>
    </div>

    ${format === 'dual' ? `
      <div style="width: 100%; margin: 2px 0;">
        <svg id="${uniqueId}-barcode" style="max-width: 100%; height: 26px; margin: 0 auto; display: block;"></svg>
      </div>
    ` : ''}

    <div style="display: flex; justify-content: space-between; width: 100%; border-top: 1px solid #000; border-bottom: 1px solid #000; padding: 3px 0; font-size: 9.5px; font-weight: 700;">
      <span>SIZE: <strong>${escapeHtml(item.size)}</strong></span>
      <span>COLOR: <strong>${escapeHtml(item.color)}</strong></span>
    </div>

    <div style="text-align: center; width: 100%; margin-top: 3px;">
      <span style="font-size: 8px; color: #555; text-transform: uppercase; letter-spacing: 0.5px;">M.R.P. (INCL. ALL TAXES)</span>
      <div style="font-size: 16.5px; font-weight: 900; color: #000; font-family: monospace;">
        ${s.currency_symbol}${Number(item.price).toFixed(0)}
      </div>
      <span style="font-size: 8px; font-family: monospace; color: #555;">SKU: ${escapeHtml(item.sku)}</span>
    </div>
  `;

  setTimeout(() => {
    const qrEl = document.getElementById(`${uniqueId}-qr`);
    if (qrEl) {
      new QRCode(qrEl, {
        text: item.sku || 'SOL-001',
        width: 82,
        height: 82,
        colorDark: "#000000",
        colorLight: "#ffffff",
        correctLevel: QRCode.CorrectLevel.M
      });
    }

    if (format === 'dual') {
      const svgEl = document.getElementById(`${uniqueId}-barcode`);
      if (svgEl && window.JsBarcode) {
        try {
          JsBarcode(svgEl, item.sku || 'SOL-001', {
            format: "CODE128",
            width: 1.2,
            height: 20,
            displayValue: false,
            margin: 0
          });
        } catch (e) {}
      }
    }
  }, 40);

  return card;
}

function printCustomTagNow() {
  const container = document.getElementById('printable-tags-container');
  if (!container) return;

  const name = document.getElementById('tag-studio-name').value.trim() || 'SOL Garment Essential';
  const price = parseFloat(document.getElementById('tag-studio-price').value) || 0;
  const category = document.getElementById('tag-studio-category').value.trim() || 'Apparel';
  const color = document.getElementById('tag-studio-color').value.trim() || 'Standard';
  const size = state.tagStudio.selectedSize || 'M';
  const sku = document.getElementById('tag-studio-sku').value.trim() || 'SOL-001';
  const format = document.getElementById('tag-studio-format').value || 'hangtag';
  const copies = parseInt(document.getElementById('tag-studio-copies').value) || 1;

  container.innerHTML = '';

  for (let i = 0; i < copies; i++) {
    const tagCard = createTagCardElement({
      name, price, category, color, size, sku, format
    }, `print-now-${i}`);
    container.appendChild(tagCard);
  }

  // Trigger print with safety timeout
  setTimeout(() => {
    printGarmentTags();
  }, 150);
}

function addCustomTagToSheet() {
  const name = document.getElementById('tag-studio-name').value.trim() || 'SOL Garment';
  const price = parseFloat(document.getElementById('tag-studio-price').value) || 0;
  const category = document.getElementById('tag-studio-category').value.trim() || 'Apparel';
  const color = document.getElementById('tag-studio-color').value.trim() || 'Standard';
  const size = state.tagStudio.selectedSize || 'M';
  const sku = document.getElementById('tag-studio-sku').value.trim() || 'SOL-001';
  const format = document.getElementById('tag-studio-format').value || 'hangtag';
  const copies = parseInt(document.getElementById('tag-studio-copies').value) || 1;

  for (let i = 0; i < copies; i++) {
    state.tagStudio.customQueue.push({
      id: 'custom_' + Date.now() + '_' + i,
      name,
      selling_price: price,
      category,
      color,
      size,
      sku,
      format
    });
  }

  playSuccessChime();
  setTagSheetView('queue');
}

function setTagSheetView(view) {
  state.tagStudio.activeView = view;

  const btnAll = document.getElementById('tag-view-btn-all');
  const btnQueue = document.getElementById('tag-view-btn-queue');
  const clearBtn = document.getElementById('tag-clear-queue-btn');

  if (view === 'all') {
    btnAll.className = 'px-3 py-1.5 rounded-xl bg-white text-black font-extrabold text-xs transition';
    btnQueue.className = 'px-3 py-1.5 rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-400 font-bold text-xs hover:text-white transition';
    clearBtn.classList.add('hidden');
  } else {
    btnQueue.className = 'px-3 py-1.5 rounded-xl bg-white text-black font-extrabold text-xs transition';
    btnAll.className = 'px-3 py-1.5 rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-400 font-bold text-xs hover:text-white transition';
    clearBtn.classList.remove('hidden');
  }

  renderGarmentTags();
}

function filterTagSheet() {
  renderGarmentTags();
}

function clearCustomTagQueue() {
  if (confirm('Clear all customized tags from queue?')) {
    state.tagStudio.customQueue = [];
    renderGarmentTags();
  }
}

async function saveTagAsNewProduct() {
  const name = document.getElementById('tag-studio-name').value.trim();
  const price = parseFloat(document.getElementById('tag-studio-price').value) || 0;
  const category = document.getElementById('tag-studio-category').value.trim() || 'General';
  const color = document.getElementById('tag-studio-color').value.trim() || 'Standard';
  const size = state.tagStudio.selectedSize || 'Free Size';
  const sku = document.getElementById('tag-studio-sku').value.trim();

  if (!name || !sku || price <= 0) {
    alert('Please ensure style name, SKU and price are filled out.');
    return;
  }

  const payload = {
    name,
    sku,
    barcode: sku.replace(/[^0-9]/g, '') || ('890' + Math.floor(1000000 + Math.random() * 9000000)),
    category,
    size,
    color,
    brand: 'SOL',
    stock_quantity: 10,
    cost_price: Math.round(price * 0.4),
    selling_price: price,
    low_stock_threshold: 5
  };

  try {
    const res = await fetch('/api/products', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const created = await res.json();
      playSuccessChime();
      alert(`Garment style "${name}" (Size: ${size}, MRP: ${state.settings.currency_symbol}${price}) saved to Stock inventory!`);
      await loadProducts();
      await loadCategories();
      renderPosCategoryChips();
      populateTagStudioProducts();
      document.getElementById('tag-studio-select-product').value = created.id;
    } else {
      const err = await res.json();
      alert('Error saving product: ' + (err.detail || 'Failed'));
    }
  } catch (err) {
    alert('Failed to save to stock: ' + err.message);
  }
}

function openTagStudioForProduct(productId) {
  switchTab('tags');
  setTimeout(() => {
    const sel = document.getElementById('tag-studio-select-product');
    if (sel) sel.value = productId;
    loadProductIntoTagStudio(productId);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, 100);
}

function renderGarmentTags() {
  const container = document.getElementById('printable-tags-container');
  if (!container) return;
  container.innerHTML = '';

  const searchInput = document.getElementById('tag-sheet-search');
  const query = searchInput ? searchInput.value.trim().toLowerCase() : '';

  // Update counts
  const countAll = document.getElementById('tag-count-all');
  const countQueue = document.getElementById('tag-count-queue');
  if (countAll) countAll.textContent = state.allProducts.length;
  if (countQueue) countQueue.textContent = state.tagStudio.customQueue.length;

  let itemsToRender = (state.tagStudio.activeView === 'queue')
    ? state.tagStudio.customQueue
    : state.allProducts;

  if (query) {
    itemsToRender = itemsToRender.filter(it => 
      (it.name && it.name.toLowerCase().includes(query)) ||
      (it.size && it.size.toLowerCase().includes(query)) ||
      (it.sku && it.sku.toLowerCase().includes(query)) ||
      (it.category && it.category.toLowerCase().includes(query))
    );
  }

  if (itemsToRender.length === 0) {
    container.innerHTML = `
      <div class="col-span-full py-12 text-center text-xs text-zinc-500">
        <i class="fa-solid fa-tags text-2xl mb-2 block"></i>
        <span>No tags in this view. Use the Tag Studio above to customize and add tags.</span>
      </div>
    `;
    return;
  }

  itemsToRender.forEach((prod, index) => {
    const uniqueId = `sheet-tag-${prod.id || index}`;
    const tagCard = createTagCardElement({
      name: prod.name,
      price: prod.selling_price,
      category: prod.category,
      color: prod.color,
      size: prod.size,
      sku: prod.sku,
      format: prod.format || 'hangtag'
    }, uniqueId);

    // Wrapper for sheet actions (Edit in studio, print 1 copy)
    const wrapper = document.createElement('div');
    wrapper.className = 'flex flex-col items-center gap-2 group';

    wrapper.appendChild(tagCard);

    // Control bar under tag on screen (hidden on print)
    const toolbar = document.createElement('div');
    toolbar.className = 'no-print flex items-center gap-2 mt-1';
    toolbar.innerHTML = `
      <button onclick="openTagStudioForProduct(${prod.id})" class="px-2.5 py-1 rounded-lg bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 text-zinc-300 text-[10px] font-bold transition" title="Edit Name & Price in Studio">
        <i class="fa-solid fa-pen-to-square mr-1"></i> Edit
      </button>
      <button onclick="printSingleTag(${JSON.stringify(prod).replace(/"/g, '&quot;')})" class="px-2.5 py-1 rounded-lg bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 text-white text-[10px] font-bold transition" title="Print this tag">
        <i class="fa-solid fa-print"></i>
      </button>
    `;
    wrapper.appendChild(toolbar);

    container.appendChild(wrapper);
  });
}

function printSingleTag(prod) {
  const container = document.getElementById('printable-tags-container');
  if (!container) return;

  container.innerHTML = '';
  const singleTag = createTagCardElement({
    name: prod.name,
    price: prod.selling_price,
    category: prod.category,
    color: prod.color,
    size: prod.size,
    sku: prod.sku,
    format: prod.format || 'hangtag'
  }, 'single-print');

  container.appendChild(singleTag);

  setTimeout(() => {
    printGarmentTags();
    setTimeout(() => renderGarmentTags(), 800);
  }, 100);
}

function printGarmentTags() {
  document.body.classList.remove('printing-receipt');
  document.body.classList.add('printing-tags');
  window.print();
  setTimeout(() => {
    document.body.classList.remove('printing-tags');
  }, 1200);
}

// ==============================================================
// 14. MOBILE DEPLOYMENT MODAL
// ==============================================================

function openMobileDeployModal() {
  populateMobileIp();
  document.getElementById('modal-mobile-deploy').classList.remove('hidden');
}

function closeMobileDeployModal() {
  document.getElementById('modal-mobile-deploy').classList.add('hidden');
}

// Utility: HTML Escaping
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ==============================================================
// 15. SOLD PRODUCTS & SALES REPORT MODAL
// ==============================================================

state.soldProductsData = null;
state.soldActiveTab = 'items';

function openSoldProductsModal() {
  const modal = document.getElementById('modal-sold-products');
  if (modal) modal.classList.remove('hidden');
  loadSoldProductsModal();
}

function closeSoldProductsModal() {
  const modal = document.getElementById('modal-sold-products');
  if (modal) modal.classList.add('hidden');
}

async function loadSoldProductsModal() {
  try {
    const res = await fetch('/api/sales/sold-products');
    if (!res.ok) return;
    const data = await res.json();
    state.soldProductsData = data;

    // Update Header Sold Count Badge
    const headerBadge = document.getElementById('header-sold-count-badge');
    if (headerBadge) {
      headerBadge.textContent = `${data.today_units_sold} Today`;
    }

    // Update KPI Summary in modal
    const todayUnitsEl = document.getElementById('sold-stat-today-units');
    const todayRevEl = document.getElementById('sold-stat-today-rev');
    const totalUnitsEl = document.getElementById('sold-stat-total-units');
    const totalRevEl = document.getElementById('sold-stat-total-rev');

    if (todayUnitsEl) todayUnitsEl.textContent = data.today_units_sold;
    if (todayRevEl) todayRevEl.textContent = parseFloat(data.today_revenue || 0).toFixed(2);
    if (totalUnitsEl) totalUnitsEl.textContent = data.total_units_sold;
    if (totalRevEl) totalRevEl.textContent = parseFloat(data.total_revenue || 0).toFixed(2);

    renderSoldProductsUI();
  } catch (err) {
    console.error('Failed to load sold products report:', err);
  }
}

function switchSoldViewTab(tab) {
  state.soldActiveTab = tab;
  const itemsBtn = document.getElementById('sold-tab-items-btn');
  const invBtn = document.getElementById('sold-tab-invoices-btn');
  const itemsView = document.getElementById('sold-items-view');
  const invView = document.getElementById('sold-invoices-view');

  if (tab === 'items') {
    if (itemsBtn) itemsBtn.className = 'px-3 py-1.5 rounded-lg font-bold bg-white text-black transition';
    if (invBtn) invBtn.className = 'px-3 py-1.5 rounded-lg font-semibold text-zinc-400 hover:text-white transition';
    if (itemsView) itemsView.classList.remove('hidden');
    if (invView) invView.classList.add('hidden');
  } else {
    if (invBtn) invBtn.className = 'px-3 py-1.5 rounded-lg font-bold bg-white text-black transition';
    if (itemsBtn) itemsBtn.className = 'px-3 py-1.5 rounded-lg font-semibold text-zinc-400 hover:text-white transition';
    if (invView) invView.classList.remove('hidden');
    if (itemsView) itemsView.classList.add('hidden');
  }

  const searchInput = document.getElementById('sold-search-input');
  const query = searchInput ? searchInput.value.trim() : '';
  renderSoldProductsUI(query);
}

function filterSoldProductsList(query) {
  renderSoldProductsUI(query);
}

function renderSoldProductsUI(filterText = '') {
  if (!state.soldProductsData) return;
  const q = (filterText || (document.getElementById('sold-search-input') ? document.getElementById('sold-search-input').value : '')).toLowerCase().trim();

  if (state.soldActiveTab === 'items') {
    renderSoldItemsTable(q);
  } else {
    renderSoldRecentInvoices(q);
  }
}

function renderSoldItemsTable(query) {
  const tbody = document.getElementById('sold-items-table-body');
  const emptyEl = document.getElementById('sold-items-empty');
  if (!tbody) return;

  const items = (state.soldProductsData && state.soldProductsData.sold_products) || [];
  const filtered = items.filter(it => {
    if (!query) return true;
    return (
      (it.product_name && it.product_name.toLowerCase().includes(query)) ||
      (it.sku && it.sku.toLowerCase().includes(query)) ||
      (it.color && it.color.toLowerCase().includes(query)) ||
      (it.size && it.size.toLowerCase().includes(query)) ||
      (it.category && it.category.toLowerCase().includes(query))
    );
  });

  tbody.innerHTML = '';

  if (filtered.length === 0) {
    if (emptyEl) {
      emptyEl.textContent = query ? 'No matching sold products found.' : 'No items sold yet.';
      emptyEl.classList.remove('hidden');
    }
    return;
  }

  if (emptyEl) emptyEl.classList.add('hidden');

  filtered.forEach(it => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-zinc-900/60 transition';

    const stockLeft = it.stock_left !== null && it.stock_left !== undefined ? it.stock_left : 'N/A';
    const stockClass = (stockLeft !== 'N/A' && stockLeft <= 0)
      ? 'text-red-400 bg-red-950/80 border border-red-800'
      : (stockLeft !== 'N/A' && stockLeft <= 5)
        ? 'text-amber-400 bg-amber-950/80 border border-amber-800'
        : 'text-zinc-300 bg-zinc-900 border border-zinc-800';

    const lastSoldStr = it.last_sold ? new Date(it.last_sold).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-';

    tr.innerHTML = `
      <td class="py-2.5 px-3">
        <div class="font-bold text-white">${escapeHtml(it.product_name)}</div>
        <div class="text-[10px] text-zinc-500 uppercase font-mono">${escapeHtml(it.category || 'Apparel')}</div>
      </td>
      <td class="py-2.5 px-2">
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="font-mono text-zinc-300 text-[11px]">${escapeHtml(it.sku)}</span>
          ${it.size ? `<span class="bg-zinc-800 text-white font-bold px-1.5 py-0.2 rounded text-[10px]">${escapeHtml(it.size)}</span>` : ''}
          ${it.color ? `<span class="text-zinc-400 text-[10px]">${escapeHtml(it.color)}</span>` : ''}
        </div>
      </td>
      <td class="py-2.5 px-2 text-center font-mono font-extrabold text-emerald-400 text-sm">
        ${it.units_sold}
      </td>
      <td class="py-2.5 px-2 text-right font-mono font-bold text-white text-xs">
        ${state.settings.currency_symbol || '₹'}${parseFloat(it.revenue || 0).toFixed(2)}
      </td>
      <td class="py-2.5 px-2 text-center">
        <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded ${stockClass}">${stockLeft}</span>
      </td>
      <td class="py-2.5 px-3 text-right text-zinc-400 font-mono text-[11px]">
        ${lastSoldStr}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function renderSoldRecentInvoices(query) {
  const tbody = document.getElementById('sold-invoices-table-body');
  if (!tbody) return;

  const sales = (state.soldProductsData && state.soldProductsData.recent_sales) || [];
  const filtered = sales.filter(s => {
    if (!query) return true;
    return (
      (s.invoice_number && s.invoice_number.toLowerCase().includes(query)) ||
      (s.customer_name && s.customer_name.toLowerCase().includes(query)) ||
      (s.customer_phone && s.customer_phone.includes(query)) ||
      (s.payment_method && s.payment_method.toLowerCase().includes(query))
    );
  });

  tbody.innerHTML = '';

  if (filtered.length === 0) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="6" class="py-8 text-center text-zinc-500 text-xs">No recent invoices found.</td>`;
    tbody.appendChild(tr);
    return;
  }

  filtered.forEach(s => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-zinc-900/60 transition';

    const dateStr = s.created_at ? new Date(s.created_at).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';

    tr.innerHTML = `
      <td class="py-2.5 px-3">
        <div class="font-mono font-bold text-white text-xs">${escapeHtml(s.invoice_number)}</div>
        <div class="text-[10px] text-zinc-500 font-mono">${dateStr}</div>
      </td>
      <td class="py-2.5 px-2">
        <div class="font-bold text-white">${escapeHtml(s.customer_name || 'Walk-in Guest')}</div>
        ${s.customer_phone ? `<div class="text-[10px] text-zinc-400 font-mono">${escapeHtml(s.customer_phone)}</div>` : ''}
      </td>
      <td class="py-2.5 px-2 text-center font-mono font-bold text-white">
        ${s.item_count || 1}
      </td>
      <td class="py-2.5 px-2">
        <span class="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-300 border border-zinc-800">${escapeHtml(s.payment_method || 'UPI')}</span>
      </td>
      <td class="py-2.5 px-2 text-right font-mono font-extrabold text-emerald-400 text-xs">
        ${state.settings.currency_symbol || '₹'}${parseFloat(s.grand_total || 0).toFixed(2)}
      </td>
      <td class="py-2.5 px-3 text-center">
        <div class="flex items-center justify-center gap-1.5">
          <button onclick="viewSaleInvoiceDetails(${s.id})" title="View Invoice Receipt" class="p-1.5 rounded-lg bg-zinc-900 hover:bg-white hover:text-black border border-zinc-800 text-zinc-300 transition text-xs">
            <i class="fa-solid fa-eye"></i>
          </button>
          <button onclick="reprintInvoiceById(${s.id})" title="Print Thermal Receipt" class="p-1.5 rounded-lg bg-zinc-900 hover:bg-white hover:text-black border border-zinc-800 text-zinc-300 transition text-xs">
            <i class="fa-solid fa-print"></i>
          </button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function viewSaleInvoiceDetails(saleId) {
  try {
    const res = await fetch(`/api/invoices/${saleId}`);
    if (res.ok) {
      const sale = await res.json();
      state.lastCompletedInvoice = sale;
      openInvoiceSuccessModal(sale);
    } else {
      alert('Could not load invoice details.');
    }
  } catch (e) {
    alert('Error loading invoice: ' + e.message);
  }
}

async function reprintInvoiceById(saleId) {
  try {
    const res = await fetch(`/api/invoices/${saleId}`);
    if (res.ok) {
      const sale = await res.json();
      state.lastCompletedInvoice = sale;
      printLastThermalReceipt();
    } else {
      alert('Could not fetch invoice details for printing.');
    }
  } catch (e) {
    alert('Error loading invoice: ' + e.message);
  }
}
