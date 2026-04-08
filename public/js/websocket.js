/* ── 初创公司 · WebSocket 连接管理 ──────────────────────────────────── */

class GameWebSocket {
  constructor() {
    this.ws = null;
    this.playerId = null;
    this.handlers = {};       // type → [callback, ...]
    this._openHandlers = [];  // 连接成功的一次性回调
    this._disconnectShown = false;
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}/ws`;
    this.ws = new WebSocket(url);
    this._disconnectShown = false;

    this.ws.onopen = () => {
      this._hideDisconnectOverlay();
      const cbs = this._openHandlers.splice(0);
      cbs.forEach(fn => fn());
    };

    this.ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }
      const list = this.handlers[msg.type] || [];
      list.forEach(fn => fn(msg));
    };

    this.ws.onclose = () => {
      if (!this._disconnectShown) {
        this._disconnectShown = true;
        this._showDisconnectOverlay();
      }
    };

    this.ws.onerror = () => {
      // onerror is always followed by onclose, handled there
    };
  }

  /** 注册消息处理器（可多次注册同一类型）*/
  on(type, callback) {
    if (type === 'open') {
      // 特殊：open 事件
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        callback();
      } else {
        this._openHandlers.push(callback);
      }
      return;
    }
    if (!this.handlers[type]) this.handlers[type] = [];
    this.handlers[type].push(callback);
  }

  /** 移除某类型的所有处理器 */
  off(type) {
    delete this.handlers[type];
  }

  /** 发送消息 */
  send(type, data = {}) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[WS] 未连接，无法发送:', type);
      return;
    }
    this.ws.send(JSON.stringify({ type, ...data }));
  }

  /** 主动断开 */
  disconnect() {
    if (this.ws) {
      this._disconnectShown = true; // 不弹断线提示
      this.ws.close();
      this.ws = null;
    }
  }

  /** 是否已连接 */
  get connected() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  // ── 断线遮罩 ────────────────────────────────────────────────────────────

  _showDisconnectOverlay() {
    if (document.getElementById('ws-disconnect-overlay')) return;
    const div = document.createElement('div');
    div.id = 'ws-disconnect-overlay';
    div.className = 'disconnect-overlay';
    div.innerHTML = `
      <div style="font-size:48px">📡</div>
      <h2>连接已断开</h2>
      <p>与服务器的连接中断，请刷新页面重试</p>
      <button class="btn btn-primary" onclick="location.reload()">刷新页面</button>
    `;
    document.body.appendChild(div);
  }

  _hideDisconnectOverlay() {
    const el = document.getElementById('ws-disconnect-overlay');
    if (el) el.remove();
  }
}

// ── 全局单例 ──────────────────────────────────────────────────────────────
const gameWS = new GameWebSocket();

// ── Toast 工具函数（全局可用）────────────────────────────────────────────
function showToast(message, type = 'info', duration = 3000) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('removing');
    toast.addEventListener('animationend', () => toast.remove());
  }, duration);
}
