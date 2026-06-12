(function() {
  'use strict';

  // ── State ──
  var _lastSignal = null;
  var _lastSignalKey = '';
  var _alertSoundCtx = null;
  var _toasts = [];

  function onReady(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  function setText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function fmtN(n) {
    return n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }

  // ── Audio Alert Beep ──
  function getAudioCtx() {
    if (!_alertSoundCtx) {
      _alertSoundCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return _alertSoundCtx;
  }

  function playAlertBeep(type) {
    // type: 'new' = new signal, 'change' = direction changed, 'update' = strength changed
    if (!document.getElementById('lsAlertSound') || !document.getElementById('lsAlertSound').checked) return;
    try {
      var ctx = getAudioCtx();
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);

      if (type === 'new') {
        // Double high-low beep for new signal
        osc.frequency.value = 880;
        gain.gain.value = 0.3;
        osc.start(ctx.currentTime);
        osc.frequency.setValueAtTime(880, ctx.currentTime);
        osc.frequency.setValueAtTime(660, ctx.currentTime + 0.1);
        osc.frequency.setValueAtTime(880, ctx.currentTime + 0.2);
        gain.gain.setValueAtTime(0.3, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
        osc.stop(ctx.currentTime + 0.4);
      } else if (type === 'change') {
        // Rising chirp for direction change
        osc.type = 'sine';
        osc.frequency.value = 440;
        osc.frequency.linearRampToValueAtTime(880, ctx.currentTime + 0.15);
        osc.frequency.linearRampToValueAtTime(440, ctx.currentTime + 0.3);
        gain.gain.value = 0.25;
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.35);
      } else {
        // Short tick for update
        osc.frequency.value = 660;
        gain.gain.value = 0.15;
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.1);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.1);
      }
    } catch(e) {}
  }

  // ── Browser Notification ──
  function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }

  function sendBrowserNotification(sig) {
    if (!document.getElementById('lsAlertNotif') || !document.getElementById('lsAlertNotif').checked) return;
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    try {
      var emoji = sig.direction === 'long' ? '\u{1F7E2}' : '\u{1F534}';
      var title = emoji + ' ' + sig.direction.toUpperCase() + ' Signal — ' + sig.symbol;
      var body = 'Confidence: ' + sig.confidence + ' | Entry: $' + fmtN(sig.entry);
      if (sig.sl) body += '\nSL: $' + fmtN(sig.sl) + ' | TP: $' + fmtN(sig.tp);
      body += '\nR:R = 1:' + (sig.rr || 0).toFixed(1);
      new Notification(title, { body: body, icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">\u26A1</text></svg>' });
    } catch(e) {}
  }

  // ── Visual Toast ──
  function showToast(sig) {
    if (!document.getElementById('lsAlertToast') || !document.getElementById('lsAlertToast').checked) return;
    var container = document.getElementById('lsToastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'lsToastContainer';
      container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;max-width:380px';
      document.body.appendChild(container);
    }

    var emoji = sig.direction === 'long' ? '\u{1F7E2}' : '\u{1F534}';
    var color = sig.direction === 'long' ? '#10b981' : '#f43f5e';
    var bgColor = sig.direction === 'long' ? 'rgba(16,185,129,0.12)' : 'rgba(244,63,94,0.12)';

    var toast = document.createElement('div');
    toast.style.cssText = 'pointer-events:auto;background:' + bgColor + ';border:1px solid ' + color + '40;border-radius:10px;padding:12px 16px;backdrop-filter:blur(20px);box-shadow:0 8px 32px rgba(0,0,0,0.4);display:flex;align-items:center;gap:10px;animation:lsToastIn 0.3s ease-out;cursor:pointer;transition:opacity 0.3s';
    toast.innerHTML = '<span style="font-size:20px">' + emoji + '</span>' +
      '<div style="flex:1;min-width:0">' +
        '<div style="font-size:12px;font-weight:700;color:' + color + '">' + sig.direction.toUpperCase() + ' Signal — ' + sig.symbol + '</div>' +
        '<div style="font-size:10px;color:#94a3b8;margin-top:2px">' + sig.confidence + ' | Entry $' + fmtN(sig.entry) + ' | R:R 1:' + (sig.rr || 0).toFixed(1) + '</div>' +
      '</div>' +
      '<span style="font-size:10px;color:#64748b;white-space:nowrap">\u2192 click to view</span>';

    toast.onclick = function() {
      // Switch to Live Signals tab
      var tabBtn = document.querySelector('[data-tab="live-signals"]');
      if (tabBtn) tabBtn.click();
      toast.style.opacity = '0';
      setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
    };

    container.appendChild(toast);

    // Stack limit + auto dismiss
    _toasts.push(toast);
    if (_toasts.length > 5) {
      var old = _toasts.shift();
      if (old && old.parentNode) old.parentNode.removeChild(old);
    }
    setTimeout(function() {
      toast.style.opacity = '0';
      setTimeout(function() {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
        var idx = _toasts.indexOf(toast);
        if (idx > -1) _toasts.splice(idx, 1);
      }, 300);
    }, 8000);
  }

  // ── Forward to Telegram/Email ──
  function forwardAlert(sig) {
    if (!document.getElementById('lsAlertServer') || !document.getElementById('lsAlertServer').checked) return;
    var symbolEl = document.getElementById('symbolSelect');
    var intervalEl = document.getElementById('intervalSelect');
    fetch('/api/signal-alert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: sig.symbol || (symbolEl ? symbolEl.value : 'BTCUSDT'),
        interval: sig.interval || (intervalEl ? intervalEl.value : '15m'),
        signal: sig.signal,
        direction: sig.direction,
        confidence: sig.confidence,
        entry: sig.entry,
        sl: sig.sl,
        tp: sig.tp,
        rr: sig.rr,
        components: sig.components || []
      })
    }).then(function(r) { return r.json(); }).then(function(d) {
      if (d && d.success && d.sent) {
        var alertEl = document.getElementById('lsAlertStatus');
        if (alertEl) {
          var parts = [];
          if (d.results && d.results.telegram) parts.push('TG');
          if (d.results && d.results.email) parts.push('Email');
          if (parts.length) {
            alertEl.textContent = '\u2705 Sent via ' + parts.join(', ');
            alertEl.style.color = '#10b981';
            setTimeout(function() { alertEl.textContent = ''; }, 5000);
          }
        }
      }
    }).catch(function() {});
  }

  // ── Signal Change Detection ──
  function detectSignalChange(newSig) {
    if (!newSig || !newSig.success) return 'none';

    var newKey = [
      newSig.signal, newSig.direction, newSig.confidence,
      newSig.entry ? Math.round(newSig.entry * 100) : 0
    ].join('|');

    if (!_lastSignal) {
      // First time seeing a signal
      if (newSig.signal === 'TRADE') {
        _lastSignal = newSig;
        _lastSignalKey = newKey;
        return 'new';
      }
      return 'none';
    }

    var oldKey = _lastSignalKey;
    _lastSignal = newSig;
    _lastSignalKey = newKey;

    if (newKey === oldKey) return 'same';

    var oldDir = _lastSignal.direction;
    var newDir = newSig.direction;

    // Direction change is highest priority
    if (oldDir !== newDir && newSig.signal === 'TRADE') return 'direction-change';

    // No signal -> signal
    if (newSig.signal === 'TRADE') return 'new';

    // Signal -> no signal
    if (newSig.signal !== 'TRADE') return 'cleared';

    return 'update';
  }

  // ── Update Hero ──
  function updateHero(sig) {
    var iconEl = document.getElementById('lsSignalIcon');
    var labelEl = document.getElementById('lsSignalLabel');
    var descEl = document.getElementById('lsSignalDesc');
    var dirValEl = document.getElementById('lsDirValue');
    var dirCardEl = document.getElementById('lsDirCard');
    var confValEl = document.getElementById('lsConfValue');
    var badgeEl = document.getElementById('liveSignalBadge');

    var dir = sig.direction;
    var conf = sig.confidence || 'NONE';
    var signal = sig.signal || 'NO_TRADE';

    if (signal === 'TRADE' && dir === 'long') {
      if (iconEl) iconEl.textContent = '\u{1F7E2}';
      if (labelEl) { labelEl.textContent = 'LONG Signal Active'; labelEl.style.color = '#10b981'; }
      if (descEl) descEl.textContent = (sig.component_count || 0) + '/3 components aligned bullish \u2014 ' + conf + ' confidence';
      if (dirValEl) { dirValEl.textContent = 'LONG'; dirValEl.style.color = '#10b981'; }
      if (dirCardEl) dirCardEl.style.borderColor = 'rgba(16,185,129,0.4)';
      if (badgeEl) { badgeEl.textContent = 'L'; badgeEl.style.background = 'rgba(16,185,129,0.2)'; badgeEl.style.color = '#10b981'; }
    } else if (signal === 'TRADE' && dir === 'short') {
      if (iconEl) iconEl.textContent = '\u{1F534}';
      if (labelEl) { labelEl.textContent = 'SHORT Signal Active'; labelEl.style.color = '#f43f5e'; }
      if (descEl) descEl.textContent = (sig.component_count || 0) + '/3 components aligned bearish \u2014 ' + conf + ' confidence';
      if (dirValEl) { dirValEl.textContent = 'SHORT'; dirValEl.style.color = '#f43f5e'; }
      if (dirCardEl) dirCardEl.style.borderColor = 'rgba(244,63,94,0.4)';
      if (badgeEl) { badgeEl.textContent = 'S'; badgeEl.style.background = 'rgba(244,63,94,0.2)'; badgeEl.style.color = '#f43f5e'; }
    } else {
      if (iconEl) iconEl.textContent = '\u23F8\uFE0F';
      if (labelEl) { labelEl.textContent = 'No Active Signal'; labelEl.style.color = ''; }
      var reason = (sig.reasoning && sig.reasoning[0]) || 'Components don\'t agree';
      if (descEl) descEl.textContent = reason;
      if (dirValEl) { dirValEl.textContent = '\u2014'; dirValEl.style.color = ''; }
      if (dirCardEl) dirCardEl.style.borderColor = '';
      if (badgeEl) { badgeEl.textContent = '\u2014'; badgeEl.style.background = ''; badgeEl.style.color = ''; }
    }

    if (confValEl) {
      confValEl.textContent = conf;
      var confColors = { 'HIGH': '#10b981', 'MEDIUM': '#f59e0b', 'LOW': '#f97316', 'NONE': '#f43f5e' };
      confValEl.style.color = confColors[conf] || '#64748b';
    }
  }

  // ── Update Trade Setup ──
  function updateTradeSetup(sig) {
    setText('lsEntry', sig.entry ? '$' + fmtN(sig.entry) : '\u2014');
    setText('lsSetupTime', sig.atr ? 'ATR(14): $' + fmtN(sig.atr) : '\u2014');

    if (sig.sl && sig.tp) {
      setText('lsSL', '$' + fmtN(sig.sl));
      setText('lsTP', '$' + fmtN(sig.tp));
      var slDist = Math.abs(sig.entry - sig.sl);
      var tpDist = Math.abs(sig.tp - sig.entry);
      setText('lsSLDist', '$' + fmtN(slDist) + ' (' + (slDist / sig.entry * 100).toFixed(2) + '%)');
      setText('lsTPDist', '$' + fmtN(tpDist) + ' (' + (tpDist / sig.entry * 100).toFixed(2) + '%)');
      setText('lsRR', '1 : ' + (sig.rr || 0).toFixed(1));
      var risk = 10000 * 0.02;
      var posSize = risk / slDist;
      var profit = posSize * tpDist;
      setText('lsPosSize', posSize.toFixed(4));
      setText('lsRiskAmt', '$' + fmtN(risk));
      setText('lsProfit', '+$' + fmtN(profit));
    } else {
      setText('lsSL', '\u2014');
      setText('lsTP', '\u2014');
      setText('lsSLDist', '\u2014');
      setText('lsTPDist', '\u2014');
      setText('lsRR', '\u2014');
      setText('lsPosSize', '\u2014');
      setText('lsRiskAmt', '\u2014');
      setText('lsProfit', '\u2014');
    }
  }

  // ── Update Components ──
  function updateComponents(sig) {
    var compEl = document.getElementById('lsComponents');
    if (compEl && sig.components) {
      compEl.innerHTML = sig.components.map(function(c) {
        var color = c.active ? '#10b981' : '#64748b';
        return '<div class="ls-comp-card ' + (c.active ? 'active' : 'inactive') + '">' +
          '<div class="ls-comp-header">' +
            '<span class="ls-comp-name">' + c.name + '</span>' +
            '<span class="ls-comp-weight">w=' + (c.weight * 100).toFixed(0) + '%</span>' +
            '<span class="ls-comp-status" style="color:' + color + '">' + (c.active ? '\u2705 ACTIVE' : '\u2B1C INACTIVE') + '</span>' +
          '</div>' +
          '<div class="ls-comp-evidence" style="color:' + (c.active ? '#94a3b8' : '#475569') + '">' + c.evidence + '</div>' +
          (c.active ? '<div class="ls-comp-strength"><div class="ls-comp-strength-bar" style="width:' + (c.strength * 100).toFixed(0) + '%;background:' + color + '"></div></div>' : '') +
        '</div>';
      }).join('');
    }
  }

  // ── Update Market Regime ──
  function updateRegime(sig) {
    var regime = sig.regime || {};
    setText('lsADX', (regime.adx || 0).toFixed(1));
    setText('lsBBWidth', (regime.bb_width || 0).toFixed(2) + '%');
    setText('lsATR', sig.atr ? '$' + fmtN(sig.atr) : '\u2014');
    var adxEl = document.getElementById('lsADX');
    if (adxEl) adxEl.style.color = (regime.adx || 0) >= 25 ? '#10b981' : (regime.adx || 0) >= 20 ? '#f59e0b' : '#f43f5e';

    var volEl = document.getElementById('lsVolRatio');
    if (volEl) {
      var regimeLabel = (regime.regime || 'unknown').charAt(0).toUpperCase() + (regime.regime || 'unknown').slice(1);
      volEl.textContent = regimeLabel;
      volEl.style.color = regime.regime === 'trending' ? '#10b981' : regime.regime === 'squeeze' ? '#f43f5e' : '#f59e0b';
    }
  }

  // ── Update Delta Patterns ──
  function updateDelta(sig) {
    var deltaEl = document.getElementById('lsDeltaPatterns');
    if (deltaEl && sig.deltaPatterns) {
      if (sig.deltaPatterns.length > 0) {
        deltaEl.innerHTML = sig.deltaPatterns.map(function(p) {
          var dColor = p.direction === 'bullish' ? '#10b981' : '#f43f5e';
          return '<div class="ls-delta-card" style="border-left-color:' + dColor + '">' +
            '<div class="ls-delta-name">' + p.name + '</div>' +
            '<div class="ls-delta-desc">' + p.description + '</div>' +
            '<div class="ls-delta-insight" style="color:' + dColor + '">' + p.insight + '</div>' +
          '</div>';
        }).join('');
      } else {
        deltaEl.innerHTML = '<div style="color:#64748b;font-size:11px;padding:8px">No delta patterns active</div>';
      }
    }
  }

  // ── Update Reasoning ──
  function updateReasoning(sig) {
    var reasonEl = document.getElementById('lsReasoning');
    if (reasonEl && sig.reasoning) {
      reasonEl.innerHTML = sig.reasoning.map(function(r, i) {
        return '<div class="ls-rule"><span class="ls-rule-num">' + (i + 1) + '</span><span>' + r + '</span></div>';
      }).join('');
    }
  }

  // ── Update timestamp ──
  function updateTimestamp() {
    var el = document.getElementById('lsSetupTime');
    if (el) {
      var now = new Date();
      el.textContent = 'Updated ' + now.toLocaleTimeString();
    }
  }

  // ── Main signal update handler ──
  function updateFromSignal(sig) {
    if (!sig || !sig.success) return;

    // Detect signal changes
    var changeType = detectSignalChange(sig);

    // Always update the UI
    sig.symbol = document.getElementById('symbolSelect') ? document.getElementById('symbolSelect').value : 'BTCUSDT';
    sig.interval = document.getElementById('intervalSelect') ? document.getElementById('intervalSelect').value : '15m';

    updateHero(sig);
    updateSignalBar(sig);
    updateTradeSetup(sig);
    updateComponents(sig);
    updateRegime(sig);
    updateDelta(sig);
    updateReasoning(sig);
    updateTimestamp();

    // Fire alerts based on change type
    if (changeType === 'new' || changeType === 'direction-change') {
      playAlertBeep(changeType === 'new' ? 'new' : 'change');
      sendBrowserNotification(sig);
      showToast(sig);
      forwardAlert(sig);

      // Update last signal status
      var statusEl = document.getElementById('lsAlertStatus');
      if (statusEl && changeType === 'direction-change') {
        statusEl.textContent = '\u{1F504} Direction changed to ' + sig.direction.toUpperCase();
        statusEl.style.color = '#f59e0b';
      }
    } else if (changeType === 'cleared') {
      playAlertBeep('update');
      var statusEl = document.getElementById('lsAlertStatus');
      if (statusEl) {
        statusEl.textContent = '\u274C Signal cleared';
        statusEl.style.color = '#f43f5e';
        setTimeout(function() { statusEl.textContent = ''; }, 5000);
      }
    }
  }

  // ── Fetch signal from API ──
  function fetchSignal() {
    var symbolEl = document.getElementById('symbolSelect');
    var intervalEl = document.getElementById('intervalSelect');
    var symbol = symbolEl ? symbolEl.value : 'BTCUSDT';
    var interval = intervalEl ? intervalEl.value : '15m';

    fetch('/api/signal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: symbol, interval: interval })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data && data.success) updateFromSignal(data);
    })
    .catch(function() {});
  }

  // ── Initialize ──
  function initLiveSignals() {
    // Request notification permission on load
    requestNotificationPermission();

    // View button on floating signal bar
    var fabGoBtn = document.getElementById("lsFabGoBtn");
    if (fabGoBtn) {
      fabGoBtn.addEventListener("click", function() {
        var tabBtn = document.querySelector("[data-tab=\"live-signals\"]");
        if (tabBtn) tabBtn.click();
      });
    }

    // Inject toast animation CSS if not present
    if (!document.getElementById('lsToastCSS')) {
      var style = document.createElement('style');
      style.id = 'lsToastCSS';
      style.textContent = '@keyframes lsToastIn{from{opacity:0;transform:translateX(40px)}to{opacity:1;transform:translateX(0)}}';
      document.head.appendChild(style);
    }

    // Seed initial signal state to prevent duplicate alert on first load
    var symbolEl = document.getElementById('symbolSelect');
    var intervalEl = document.getElementById('intervalSelect');
    var symbol = symbolEl ? symbolEl.value : 'BTCUSDT';
    var interval = intervalEl ? intervalEl.value : '15m';
    fetch('/api/signal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: symbol, interval: interval })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data && data.success) {
        // Seed state WITHOUT firing alerts
        _lastSignalKey = [
          data.signal, data.direction, data.confidence,
          data.entry ? Math.round(data.entry * 100) : 0
        ].join('|');
        _lastSignal = data;
        // Now update UI
        updateFromSignal(data);
      }
    })
    .catch(function() {});

    // Intercept quick-scan to also trigger signal generation
    var origFetch = window.fetch;
    window.fetch = function() {
      return origFetch.apply(this, arguments).then(function(response) {
        var url = arguments[0];
        if (typeof url === 'string' && url.indexOf('/api/quick-scan') !== -1) {
          response.clone().json().then(function(d) {
            if (d && d.success) {
              setTimeout(fetchSignal, 300);
            }
          }).catch(function() {});
        }
        return response;
      });
    };

    // Also listen for scan button click
    var scanBtn = document.getElementById('scanBtn');
    if (scanBtn) {
      scanBtn.addEventListener('click', function() {
        setTimeout(fetchSignal, 1500);
      });
    }
  }

  onReady(function() { setTimeout(initLiveSignals, 500); });
})();
