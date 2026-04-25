/* ── 初创公司 · 游戏主逻辑 & 渲染 ────────────────────────────────────── */

// ── 常量 ────────────────────────────────────────────────────────────────
const ANIMALS = ['🦒', '🐶', '🦢', '🐙', '🦛', '🐘'];
// 各动物公司总牌数（用于 UI 展示 持有/总数）
const ANIMAL_TOTAL = { '🦒': 5, '🐶': 6, '🦢': 7, '🐙': 8, '🦛': 9, '🐘': 10 };
const SLOT_ORDER = [1, 2, 5, 6, 3, 4];   // 对手槽位填充顺序
const AVATAR_COLORS = ['#4a7c41','#7b42a8','#a84242','#427ba8','#a88442','#428078','#a87242','#6a42a8'];

// ── 服务器状态 ────────────────────────────────────────────────────────
let myId         = null;
let myRoomCode   = null;
let gameState    = null;
let yourTurnInfo = null;

// ── 选中状态（交互层，不影响服务器状态） ─────────────────────────────
let selDeck   = false;   // 牌堆是否被选中
let selMktIdx = -1;      // 被选中的市场卡索引，-1=无
let selHndIdx = -1;      // 被选中的手牌索引，-1=无

// ── 初始化 ──────────────────────────────────────────────────────────────
(function init() {
  const params = new URLSearchParams(location.search);
  myRoomCode = params.get('code') || sessionStorage.getItem('room_code');
  const name  = sessionStorage.getItem('player_name');

  if (!myRoomCode || !name) {
    _setText('turn-text', '⚠ 缺少房间信息，请从首页重新进入');
    return;
  }

  // WS 消息处理器
  gameWS.on('room_update',         _onRoomUpdate);
  gameWS.on('game_start',          (m) => { _dbg('sys', '游戏开始'); _onGameState(m.game_state); });
  gameWS.on('game_state',          (m) => _onGameState(m.state));
  gameWS.on('your_turn',           _onYourTurn);
  gameWS.on('action_result',       (m) => { if (!m.success) showToast(m.message, 'error'); });
  gameWS.on('game_end',            _onGameEnd);
  gameWS.on('game_aborted',        (m) => showToast('游戏终止：' + m.reason, 'error', 5000));
  gameWS.on('player_disconnected', (m) => showToast('玩家 ' + m.player_name + ' 断线', 'error'));
  gameWS.on('error',               (m) => showToast(m.message, 'error'));

  // 连接
  gameWS.connect();
  gameWS.on('open', () => {
    _setConnBadge(true);
    gameWS.send('join_room', { room_code: myRoomCode, player_name: name });
  });

  // 事件委托：市场区域（容器不会被重建）
  document.getElementById('market-grid').addEventListener('click', _onMktClick);
  // 事件委托：手牌区域
  document.getElementById('hand-area').addEventListener('click', _onHndClick);
  // 操作按钮
  document.getElementById('btn-play-market').addEventListener('click', _onPlayMkt);
  document.getElementById('btn-play-area').addEventListener('click', _onPlayArea);

  // ` 键切换调试面板
  document.addEventListener('keydown', e => {
    if (e.key === '`') {
      const p = document.getElementById('debug-panel');
      p.style.display = (p.style.display === 'none') ? '' : 'none';
    }
  });

  _initLogDrag();
})();

// ── 消息处理 ────────────────────────────────────────────────────────────
function _onRoomUpdate(msg) {
  if (!myId) {
    const name = sessionStorage.getItem('player_name');
    const me   = (msg.players || []).find(p => p.name === name);
    if (me) myId = me.id;
  }
  _dbg('room', '玩家：' + (msg.players || []).map(p => p.name).join(', '));
}

function _onGameState(state) {
  if (!state) return;

  if (!myId) {
    const name = sessionStorage.getItem('player_name');
    const me   = (state.players || []).find(p => p.name === name);
    if (me) myId = me.id;
  }

  // 轮到别人：清空选中 & yourTurnInfo
  if (myId && state.current_player_id !== myId) {
    yourTurnInfo = null;
    _resetSel();
  }

  // 检测反垄断标记变化 → toast 提示
  _checkAntiChange(gameState, state);

  gameState = state;
  renderAll(state);

  const el = document.getElementById('debug-json');
  if (el) el.textContent = JSON.stringify(state, null, 2);
  _dbg('recv', 'phase=' + state.turn_phase + ' curr=' + state.current_player_name);
}

function _onYourTurn(msg) {
  yourTurnInfo = msg;
  _resetSel();   // 每个新阶段清空选中
  _dbg('turn', '你的回合 phase=' + msg.phase + ' cost=' + msg.draw_cost);
  if (gameState) renderAll(gameState);
}

function _onGameEnd(msg) {
  _dbg('end', '游戏结束，胜者：' + msg.winner_name);
  _renderGameEnd(msg);
}

// ════════════════════════════════════════════════════════════════════════
// 主渲染入口（幂等，每次完整重建 DOM 后恢复选中视觉）
// ════════════════════════════════════════════════════════════════════════
function renderAll(state) {
  _renderTurnBanner(state);
  _renderOpponents(state);
  _renderMarket(state);     // 内部调用 _applySel()
  _renderSelfPanel(state);
  _renderHand(state);       // 内部调用 _applySel() + _updateActionBtns()
  _renderActionBar(state);  // 内部调用 _updateActionBtns()
  _renderActionLog(state);
}

// ── 回合指示器 ──────────────────────────────────────────────────────────
function _renderTurnBanner(state) {
  const banner = document.getElementById('turn-banner');
  const textEl = document.getElementById('turn-text');
  const isMyTurn = state.current_player_id === myId;

  if (state.phase === 'ended') {
    banner.className = 'turn-banner';
    textEl.textContent = '🏁 游戏结束';
    return;
  }

  if (isMyTurn) {
    banner.className = 'turn-banner my-turn';
    if (state.turn_phase === 'draw') {
      const cost = yourTurnInfo != null ? yourTurnInfo.draw_cost : '?';
      const hint = (yourTurnInfo?.can_draw === false)
        ? `资金不足，只能取市场卡`
        : `点击牌堆摸牌（费用 ${cost} 💰）或点击市场卡`;
      textEl.innerHTML = '▶ 你的回合 &nbsp;·&nbsp; 获取卡牌 — ' + hint;
    } else {
      textEl.innerHTML = '▶ 你的回合 &nbsp;·&nbsp; 打出卡牌 — 点击手牌选中，再点操作按钮';
    }
  } else {
    banner.className = 'turn-banner waiting';
    textEl.textContent = '等待 ' + (state.current_player_name || '…') + ' 操作…';
  }
}

// ── 对手面板 ────────────────────────────────────────────────────────────
function _renderOpponents(state) {
  if (!state || !myId) return;
  const myIndex = state.players.findIndex(p => p.id === myId);
  if (myIndex < 0) return;

  const opponents = [];
  for (let i = 1; i < state.players.length; i++) {
    opponents.push(state.players[(myIndex + i) % state.players.length]);
  }

  SLOT_ORDER.forEach(n => {
    const el = document.getElementById('slot-' + n);
    if (el) el.style.display = 'none';
  });

  opponents.forEach((player, idx) => {
    if (idx >= SLOT_ORDER.length) return;
    const n  = SLOT_ORDER[idx];
    const el = document.getElementById('slot-' + n);
    if (!el) return;
    el.style.display = '';
    el.innerHTML = _buildOpponentHTML(player, state, n >= 5, n === 1 || n === 3);
  });
}

function _buildOpponentHTML(player, state, isTop, isLeft) {
  const isCurrent = player.id === state.current_player_id;
  const handCount = typeof player.hand === 'number'
    ? player.hand : (Array.isArray(player.hand) ? player.hand.length : 0);
  const panelCls = ['opp-panel', isCurrent ? 'is-current' : '', isTop ? 'opp-top' : 'opp-side']
    .filter(Boolean).join(' ');
  const avatarBg = _nameColor(player.name);
  const initial  = (player.name || '?')[0].toUpperCase();

  return `<div class="${panelCls}">
    <div class="opp-header">
      <div class="opp-avatar" style="background:${avatarBg}">${initial}</div>
      <div class="opp-meta">
        <div class="opp-name">${_esc(player.name)}${isCurrent ? ' <span class="cur-mark">▶</span>' : ''}</div>
        <div class="opp-stats">
          <span class="opp-coins">💰${player.coins}</span>&ensp;<span class="opp-hand">🃏${handCount}</span>
        </div>
      </div>
    </div>
    <div class="area-grid-wrap">${_buildAreaGrid(player.area || {}, player.anti_monopoly || [])}</div>
  </div>`;
}

// ── 放置区栅格 ──────────────────────────────────────────────────────────
function _buildAreaGrid(area, antiMonopoly) {
  const cells = ANIMALS.map(animal => {
    const count   = area[animal] || 0;
    const total   = ANIMAL_TOTAL[animal];
    const hasAnti = antiMonopoly.includes(animal);
    const cls = ['area-cell', count > 0 ? 'area-has' : 'area-empty', hasAnti ? 'area-anti' : '']
      .filter(Boolean).join(' ');
    const tip = `${animal} ${count}/${total}${hasAnti ? ' ★反垄断' : ''}`;
    return `<div class="${cls}" title="${tip}">
      <span class="ac-emoji">${animal}</span>
      <span class="ac-count">${count}<span class="ac-total">/${total}</span></span>
    </div>`;
  }).join('');
  return `<div class="area-grid">${cells}</div>`;
}

// ── 中央市场 ────────────────────────────────────────────────────────────
function _renderMarket(state) {
  if (!state) return;
  const grid = document.getElementById('market-grid');
  if (!grid) return;

  const isMyDraw   = _isMyDrawTurn();
  const drawCost   = yourTurnInfo != null ? yourTurnInfo.draw_cost : (state.market ? state.market.length : 0);
  const canDraw    = yourTurnInfo?.can_draw !== false;
  const blocked    = yourTurnInfo ? (yourTurnInfo.blocked_market || []) : [];
  const mktCards   = state.market || [];

  // 牌堆：我的摸牌回合且资金不足时显示 disabled
  const deckDisabled = isMyDraw && !canDraw;
  const deckCls = ['mslot deck-slot card-selectable', deckDisabled ? 'card-disabled' : '']
    .filter(Boolean).join(' ');
  const deckTip = deckDisabled ? `资金不足（需 ${drawCost} 💰）` : `摸牌 · 费用 ${drawCost} 💰`;

  let html = `<div class="${deckCls}" id="market-deck" title="${deckTip}">
    <div class="deck-body">
      <span class="deck-emoji">🃏</span>
      <div class="deck-label">余 ${state.deck_remaining} 张</div>
    </div>
    <div class="mslot-foot deck-cost">−${drawCost} 💰</div>
  </div>`;

  // 展示全部市场卡（不截断）
  mktCards.forEach((slot, i) => {
    const isBlocked = blocked.includes(i);
    const cls = ['mslot market-card-slot card-selectable', isBlocked ? 'card-disabled' : '']
      .filter(Boolean).join(' ');
    const tip = isBlocked ? '反垄断标记：不可取此牌' : `取牌 · 获得 ${slot.coins} 💰`;
    html += `<div class="${cls}" data-market-index="${i}" title="${tip}">
      <div class="mcard-body">
        <span class="mcard-total">×${ANIMAL_TOTAL[slot.card] ?? ''}</span>
        <span class="mcard-emoji">${slot.card}</span>
      </div>
      <div class="mslot-foot mcard-coins">+${slot.coins} 💰</div>
    </div>`;
  });

  // 补空格让末行对齐（3列）
  const total = 1 + mktCards.length;
  const remainder = total % 3;
  if (remainder !== 0) {
    for (let i = 0; i < 3 - remainder; i++) {
      html += `<div class="mslot empty-slot"></div>`;
    }
  }

  grid.innerHTML = html;
  _applySel();   // 恢复选中视觉
}

// ── 自己面板 ────────────────────────────────────────────────────────────
function _renderSelfPanel(state) {
  if (!myId || !state) return;
  const me = state.players.find(p => p.id === myId);
  if (!me) return;
  const panel     = document.getElementById('self-panel');
  const isCurrent = me.id === state.current_player_id;
  panel.className = 'self-panel' + (isCurrent ? ' is-current' : '');
  const avatarBg  = _nameColor(me.name);
  panel.innerHTML = `
    <div class="self-avatar" style="background:${avatarBg}">${(me.name||'?')[0].toUpperCase()}</div>
    <div class="self-identity">
      <div class="self-name">${_esc(me.name)}${isCurrent ? ' <span class="cur-mark">▶</span>' : ''}</div>
      <div class="self-coins">💰 ${me.coins} 资金</div>
    </div>
    <div class="self-area-grid">${_buildAreaGrid(me.area || {}, me.anti_monopoly || [])}</div>`;
}

// ── 手牌区 ──────────────────────────────────────────────────────────────
function _renderHand(state) {
  if (!myId || !state) return;
  const me   = state.players.find(p => p.id === myId);
  if (!me) return;
  const area = document.getElementById('hand-area');
  const hand = Array.isArray(me.hand) ? me.hand : [];

  if (hand.length === 0) {
    area.innerHTML = '<div class="hand-empty">（无手牌）</div>';
    _updateActionBtns();
    return;
  }

  const inPlay  = _isMyPlayTurn();
  const blocked = yourTurnInfo?.blocked_play_to_market || [];

  area.innerHTML = hand.slice(0, 4).map((card, i) => {
    // 非出牌回合时手牌不可选
    const selCls = inPlay ? 'card-selectable' : '';
    return `<div class="hand-card card ${selCls}" data-hand-index="${i}">
      <span class="hcard-total">×${ANIMAL_TOTAL[card] ?? ''}</span>
      <span class="hcard-emoji">${card}</span>
    </div>`;
  }).join('');

  _applySel();
  _updateActionBtns();
}

// ── 操作栏 ──────────────────────────────────────────────────────────────
function _renderActionBar(state) {
  const bar = document.getElementById('action-bar');
  if (!state || !myId) { bar.style.display = 'none'; return; }
  const show = _isMyPlayTurn();
  bar.style.display = show ? '' : 'none';
  if (show) _updateActionBtns();
}

// ════════════════════════════════════════════════════════════════════════
// 交互 — 市场区域点击（draw 阶段，双击确认）
// ════════════════════════════════════════════════════════════════════════
function _onMktClick(e) {
  if (!_isMyDrawTurn()) return;

  const slot = e.target.closest('.mslot');
  if (!slot) return;

  if (slot.id === 'market-deck') {
    // 牌堆
    if (yourTurnInfo?.can_draw === false) return;   // 资金不足
    if (selDeck) {
      // 第二次点击：执行摸牌
      gameWS.send('draw_card');
      _resetSel();
    } else {
      // 第一次点击：选中
      selDeck   = true;
      selMktIdx = -1;
      _applySel();
    }
  } else if (slot.dataset.marketIndex !== undefined) {
    // 市场卡
    if (slot.classList.contains('card-disabled')) return;
    const idx = parseInt(slot.dataset.marketIndex);
    if (selMktIdx === idx) {
      // 第二次点击：执行取牌
      gameWS.send('pick_market', { card_index: idx });
      _resetSel();
    } else {
      // 第一次点击：选中（切换）
      selMktIdx = idx;
      selDeck   = false;
      _applySel();
    }
  }
}

// ════════════════════════════════════════════════════════════════════════
// 交互 — 手牌点击（play 阶段，选中后按按钮）
// ════════════════════════════════════════════════════════════════════════
function _onHndClick(e) {
  if (!_isMyPlayTurn()) return;
  const card = e.target.closest('.hand-card');
  if (!card) return;
  const idx = parseInt(card.dataset.handIndex);
  selHndIdx = (selHndIdx === idx) ? -1 : idx;   // 再次点击=取消
  _applySel();
  _updateActionBtns();
}

// ── 出牌按钮 ─────────────────────────────────────────────────────────────
function _onPlayMkt() {
  if (selHndIdx < 0 || !_isMyPlayTurn()) return;
  gameWS.send('play_to_market', { hand_index: selHndIdx });
  _resetSel();
}

function _onPlayArea() {
  if (selHndIdx < 0 || !_isMyPlayTurn()) return;
  gameWS.send('play_to_area', { hand_index: selHndIdx });
  _resetSel();
}

// ════════════════════════════════════════════════════════════════════════
// 选中视觉同步
// ════════════════════════════════════════════════════════════════════════

/** 把 selDeck / selMktIdx / selHndIdx 映射到 .card-selected class */
function _applySel() {
  // 牌堆
  const deckEl = document.getElementById('market-deck');
  if (deckEl) deckEl.classList.toggle('card-selected', selDeck);

  // 市场卡
  document.querySelectorAll('[data-market-index]').forEach(el => {
    el.classList.toggle('card-selected', parseInt(el.dataset.marketIndex) === selMktIdx);
  });

  // 手牌
  document.querySelectorAll('.hand-card').forEach(el => {
    el.classList.toggle('card-selected', parseInt(el.dataset.handIndex) === selHndIdx);
  });
}

/** 根据当前选中状态更新操作按钮 */
function _updateActionBtns() {
  const btnMkt  = document.getElementById('btn-play-market');
  const btnArea = document.getElementById('btn-play-area');
  if (!btnMkt || !btnArea) return;

  const hasSel  = selHndIdx >= 0;
  const inPlay  = _isMyPlayTurn();
  const blocked = yourTurnInfo?.blocked_play_to_market || [];

  btnArea.disabled = !(hasSel && inPlay);
  btnMkt.disabled  = !(hasSel && inPlay) || blocked.includes(selHndIdx);
}

/** 清空所有选中状态并同步视觉 */
function _resetSel() {
  selDeck = false; selMktIdx = -1; selHndIdx = -1;
  _applySel();
  _updateActionBtns();
}

// ════════════════════════════════════════════════════════════════════════
// 反垄断标记变化提示
// ════════════════════════════════════════════════════════════════════════
function _checkAntiChange(oldState, newState) {
  if (!oldState || !newState || !myId) return;
  const oldMe = oldState.players.find(p => p.id === myId);
  const newMe = newState.players.find(p => p.id === myId);
  if (!oldMe || !newMe) return;

  const oldAnti = oldMe.anti_monopoly || [];
  const newAnti = newMe.anti_monopoly || [];

  newAnti.filter(a => !oldAnti.includes(a)).forEach(a => {
    showToast('你获得了 ' + a + ' 的反垄断标记！', 'success', 3500);
  });
  oldAnti.filter(a => !newAnti.includes(a)).forEach(a => {
    showToast('你失去了 ' + a + ' 的反垄断标记', 'info', 3500);
  });
}

// ════════════════════════════════════════════════════════════════════════
// 游戏结束
// ════════════════════════════════════════════════════════════════════════
function _renderGameEnd(msg) {
  document.getElementById('turn-banner').className = 'turn-banner';
  _setText('turn-text', '🏁 游戏结束');
  document.getElementById('action-bar').style.display = 'none';

  const names      = msg.player_names   || {};
  const preCoins   = msg.pre_coins      || {};
  const finalCoins = msg.scores         || {};
  const hands      = msg.revealed_hands || {};
  const areas      = msg.areas          || {};
  const details    = msg.company_details || {};

  const winnerPids  = Array.isArray(msg.winner)      ? msg.winner      : [msg.winner];
  const winnerLabel = Array.isArray(msg.winner_name) ? msg.winner_name.join('、') : msg.winner_name;

  const RANKS = ['🥇','🥈','🥉'];

  // ── 按最终金币排序的玩家列表
  const ranked = Object.entries(finalCoins).sort(([,a],[,b]) => b - a);

  const scoreRows = ranked.map(([pid, coins], i) => {
    const isWinner = winnerPids.includes(pid);
    const isMe     = pid === myId;
    const rank     = RANKS[i] || `${i+1}.`;
    const pre      = preCoins[pid] ?? '?';

    // 手牌 emoji 行
    const handCards = (hands[pid] || []);
    const handHtml  = handCards.length
      ? handCards.map(c => `<span class="er-card">${c}</span>`).join('')
      : '<span style="opacity:.4">（无）</span>';

    // 放置区：仅展示 count > 0 的
    const areaObj   = areas[pid] || {};
    const areaItems = Object.entries(areaObj).filter(([,v]) => v > 0);
    const areaHtml  = areaItems.length
      ? areaItems.map(([animal, cnt]) => `<span class="er-card">${animal}<sub>×${cnt}</sub></span>`).join('')
      : '<span style="opacity:.4">（空）</span>';

    return `<div class="er-row${isMe ? ' er-me' : ''}">
      <div class="er-header">
        <span class="er-rank">${rank}</span>
        <span class="er-name">${_esc(names[pid] || pid)}${isWinner ? ' 🏆' : ''}</span>
        <span class="er-coins">💰${pre} → <strong>💰${coins}</strong></span>
      </div>
      <div class="er-cards-row">
        <span class="er-label">手牌</span>${handHtml}
        <span class="er-label" style="margin-left:8px">放置</span>${areaHtml}
      </div>
    </div>`;
  }).join('');

  // ── 公司结算详情（折叠）
  const detailRows = Object.entries(details).map(([animal, d]) => {
    if (!d.major_shareholder) {
      return `<div class="cd-row"><span>${animal}</span><span style="opacity:.5">${d.reason || '无结算'}</span></div>`;
    }
    const penaltySummary = Object.entries(d.penalties || {})
      .map(([pid, n]) => `${_esc(names[pid]||pid)} -${n}💰`).join('、');
    return `<div class="cd-row">
      <span>${animal} 大股东：${_esc(d.major_shareholder_name)}</span>
      <span>${penaltySummary || '无人被收'}</span>
    </div>`;
  }).join('');

  const lobbyBtn = msg.room_code
    ? `<button class="btn btn-primary" onclick="returnToLobby('${_esc(msg.room_code)}')">↩ 返回房间</button>`
    : '';

  const overlay = document.createElement('div');
  overlay.className = 'game-end-overlay';
  overlay.innerHTML = `
    <div class="game-end-card">
      <div class="game-end-icon">🏆</div>
      <div class="game-end-title">游戏结束！</div>
      <div class="game-end-winner">获胜者：<strong>${_esc(winnerLabel)}</strong></div>
      <div class="er-list">${scoreRows}</div>
      <details class="cd-details">
        <summary>结算详情</summary>
        <div class="cd-body">${detailRows}</div>
      </details>
      <div class="game-end-btns">
        ${lobbyBtn}
        <a href="/" class="btn btn-secondary">← 返回首页</a>
      </div>
    </div>`;
  document.body.appendChild(overlay);
}

function returnToLobby(code) {
  window.location.href = `/room?code=${code}`;
}

// ════════════════════════════════════════════════════════════════════════
// 操作记录
// ════════════════════════════════════════════════════════════════════════

const ACTION_ICONS = {
  draw_card:     '🃏',
  pick_market:   '🛒',
  play_to_market:'📤',
  play_to_area:  '📥',
};

let _logCollapsed = false;
let _drawerOpen   = false;

// ── 桌面：折叠/展开（由拖拽逻辑在无移动时触发） ──────────────────────
function toggleActionLog() {
  _logCollapsed = !_logCollapsed;
  const body = document.getElementById('alp-body');
  const icon = document.getElementById('alp-toggle-icon');
  if (body) body.style.display = _logCollapsed ? 'none' : '';
  if (icon) icon.textContent   = _logCollapsed ? '▼' : '▲';
}

// ── 移动端：抽屉开/关 ────────────────────────────────────────────────
function openDrawer() {
  _drawerOpen = true;
  const drawer   = document.getElementById('alp-drawer');
  const backdrop = document.getElementById('alp-backdrop');
  if (backdrop) { backdrop.style.display = 'block'; requestAnimationFrame(() => backdrop.classList.add('open')); }
  if (drawer)   { drawer.style.display   = 'flex';  requestAnimationFrame(() => drawer.classList.add('open')); }
  const dl = document.getElementById('alp-drawer-list');
  if (dl) requestAnimationFrame(() => { dl.scrollTop = dl.scrollHeight; });
}

function closeDrawer() {
  _drawerOpen = false;
  const drawer   = document.getElementById('alp-drawer');
  const backdrop = document.getElementById('alp-backdrop');
  if (drawer)   drawer.classList.remove('open');
  if (backdrop) backdrop.classList.remove('open');
  // 动画结束后隐藏（300ms 与 CSS transition 同步）
  setTimeout(() => {
    if (!_drawerOpen) {
      if (drawer)   drawer.style.display   = 'none';
      if (backdrop) backdrop.style.display = 'none';
    }
  }, 320);
}

// ── 桌面：拖拽初始化 ─────────────────────────────────────────────────
function _initLogDrag() {
  const panel  = document.getElementById('action-log-panel');
  const header = document.getElementById('alp-header');
  if (!panel || !header) return;

  let dragging = false, hasMoved = false;
  let startX, startY, startLeft, startTop;

  header.addEventListener('mousedown', e => {
    dragging  = true;
    hasMoved  = false;
    startX    = e.clientX;
    startY    = e.clientY;
    header.style.cursor = 'grabbing';
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (!hasMoved && (Math.abs(dx) > 3 || Math.abs(dy) > 3)) {
      // 首次超过阈值才切换成 left/top 定位，单纯点击不改变锚点
      const rect  = panel.getBoundingClientRect();
      startLeft   = rect.left;
      startTop    = rect.top;
      panel.style.right  = 'auto';
      panel.style.bottom = 'auto';
      panel.style.left   = startLeft + 'px';
      panel.style.top    = startTop  + 'px';
      hasMoved = true;
    }
    if (hasMoved) {
      const maxL = window.innerWidth  - panel.offsetWidth;
      const maxT = window.innerHeight - panel.offsetHeight;
      panel.style.left = Math.max(0, Math.min(maxL, startLeft + dx)) + 'px';
      panel.style.top  = Math.max(0, Math.min(maxT, startTop  + dy)) + 'px';
    }
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    if (!hasMoved) toggleActionLog();   // 点击未移动 → 折叠/展开
    dragging = false;
    header.style.cursor = '';
  });
}

// ── 公共：构建单条记录 HTML ───────────────────────────────────────────
function _buildLogEntryHTML(entry) {
  const isMe  = entry.player_id === myId;
  const icon  = ACTION_ICONS[entry.action] || '▸';
  const color = _nameColor(entry.player_name);
  const cls   = 'alp-entry' + (isMe ? ' alp-me' : '');
  return `<div class="${cls}">
    <span class="alp-turn">T${entry.turn}</span>
    <span class="alp-avatar" style="background:${color}">${(entry.player_name||'?')[0].toUpperCase()}</span>
    <span class="alp-name">${_esc(entry.player_name)}</span>
    <span class="alp-icon">${icon}</span>
    <span class="alp-detail">${_esc(entry.detail)}</span>
  </div>`;
}

function _renderActionLog(state) {
  const log = (state && state.action_log) || [];
  const html = log.length
    ? log.map(_buildLogEntryHTML).join('')
    : '<div class="alp-empty">暂无操作记录</div>';

  // 桌面面板
  const list = document.getElementById('alp-list');
  if (list) { list.innerHTML = html; list.scrollTop = list.scrollHeight; }

  // 移动端抽屉
  const dl = document.getElementById('alp-drawer-list');
  if (dl) {
    dl.innerHTML = html;
    if (_drawerOpen) dl.scrollTop = dl.scrollHeight;
  }

  // 移动端 mini 预览（最近 3 条）
  const mini = document.getElementById('alp-mini');
  if (mini) {
    const recent = log.slice(-3);
    mini.innerHTML = recent.map(entry => {
      const color = _nameColor(entry.player_name);
      const icon  = ACTION_ICONS[entry.action] || '▸';
      return `<div class="alp-mini-entry">
        <span class="alp-mini-dot" style="background:${color}"></span>
        <span>${_esc(entry.player_name)} ${icon} ${_esc(entry.detail)}</span>
      </div>`;
    }).join('');
  }
}

// ════════════════════════════════════════════════════════════════════════
// 工具函数
// ════════════════════════════════════════════════════════════════════════

function _isMyDrawTurn() {
  return !!(gameState && myId &&
    gameState.current_player_id === myId &&
    gameState.turn_phase === 'draw');
}

function _isMyPlayTurn() {
  return !!(gameState && myId &&
    gameState.current_player_id === myId &&
    gameState.turn_phase === 'play');
}

function _nameColor(name) {
  let h = 0;
  for (let i = 0; i < (name || '').length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
}

function _esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function _setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function _setConnBadge(connected) {
  const el = document.getElementById('conn-badge');
  if (!el) return;
  el.textContent = connected ? '⬤ 已连接' : '⬤ 断线';
  el.style.color  = connected ? '#4ade80' : '#ef4444';
}

const _LOG_COLORS = { sys:'#aaa', recv:'#7ec87e', turn:'#7eb8e8', room:'#c8c87e', end:'#e8c87e', err:'#e87e7e' };
function _dbg(type, text) {
  const log = document.getElementById('debug-log');
  if (!log) return;
  const div = document.createElement('div');
  div.style.color = _LOG_COLORS[type] || '#ccc';
  div.textContent = '[' + type + '] ' + text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}
