/** 管理端页面：登录、玩家白名单、版本发布、握手日志。 */

import * as api from './api.js';

const views = {
  login: document.getElementById('login-view'),
  players: document.getElementById('players-view'),
  releases: document.getElementById('releases-view'),
  logs: document.getElementById('logs-view'),
};

function show(name) {
  Object.entries(views).forEach(([key, element]) => {
    element.classList.toggle('hidden', key !== name);
  });
  document.querySelectorAll('nav a').forEach((link) => {
    link.classList.toggle('active', link.dataset.view === name);
  });
}

function toast(message, isError = false) {
  const box = document.getElementById('toast');
  box.textContent = message;
  box.classList.toggle('error', isError);
  box.classList.remove('hidden');
  setTimeout(() => box.classList.add('hidden'), 3200);
}

function cell(text) {
  const td = document.createElement('td');
  td.textContent = text ?? '';
  return td;
}

// ── 登录 ──

document.getElementById('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    const result = await api.login(form.get('username'), form.get('password'));
    api.setToken(result.token);
    document.getElementById('who').textContent = form.get('username');
    show('players');
    await refreshPlayers();
  } catch (error) {
    document.getElementById('login-error').textContent = error.message;
  }
});

document.getElementById('logout').addEventListener('click', () => {
  api.setToken('');
  show('login');
});

document.querySelectorAll('nav a').forEach((link) => {
  link.addEventListener('click', async (event) => {
    event.preventDefault();
    show(link.dataset.view);
    if (link.dataset.view === 'players') await refreshPlayers();
    if (link.dataset.view === 'releases') await refreshReleases();
    if (link.dataset.view === 'logs') await refreshLogs();
  });
});

// ── 玩家白名单 ──

async function refreshPlayers() {
  const rows = await api.players.list();
  const body = document.getElementById('players-body');
  body.replaceChildren();
  rows.forEach((player) => {
    const tr = document.createElement('tr');
    tr.append(
      cell(player.player_id),
      cell(player.role_name || '—'),
      cell(player.nickname),
      cell(player.guild),
      cell(player.note),
    );
    tr.append(cell(player.enabled ? '启用' : '已停用'));

    const actions = document.createElement('td');
    const toggle = document.createElement('button');
    toggle.className = 'link';
    toggle.textContent = player.enabled ? '停用' : '启用';
    toggle.addEventListener('click', async () => {
      await api.players.patch(player.player_id, { enabled: !player.enabled });
      await refreshPlayers();
    });

    const issue = document.createElement('button');
    issue.className = 'link';
    issue.textContent = '签发license';
    issue.addEventListener('click', async () => {
      const license = await api.players.issueLicense(player.player_id);
      const blob = new Blob([JSON.stringify(license, null, 2)], { type: 'application/octet-stream' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `license-${player.player_id}.bin`;
      link.click();
      toast('license.bin 已下载，放进 exe 同级目录即可');
    });

    // 一键出包：服务端把当前生效版本的文件和这个玩家的 license 压好，直接下载
    const pack = document.createElement('button');
    pack.className = 'link';
    pack.textContent = '下载分发包';
    pack.addEventListener('click', async () => {
      pack.disabled = true;
      pack.textContent = '打包中…';
      try {
        await api.players.downloadPackage(player.player_id);
        toast(`${player.player_id} 的分发包已开始下载`);
      } catch (error) {
        toast(error.message, true);
      } finally {
        pack.disabled = false;
        pack.textContent = '下载分发包';
      }
    });

    const drop = document.createElement('button');
    drop.className = 'link danger';
    drop.textContent = '删除';
    drop.addEventListener('click', async () => {
      if (!confirm(`确认删除 ${player.player_id}？`)) return;
      await api.players.remove(player.player_id);
      await refreshPlayers();
    });

    actions.append(toggle, issue, pack, drop);
    tr.append(actions);
    body.append(tr);
  });
}

document.getElementById('player-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    const playerId = form.get('player_id').trim();
    await api.players.create({
      player_id: playerId,
      nickname: form.get('nickname'),
      note: form.get('note'),
    });
    event.target.reset();
    await refreshPlayers();
    if (!form.get('with_package')) return;
    try {
      await api.players.downloadPackage(playerId);
      toast(`${playerId} 的白名单已添加，分发包开始下载`);
    } catch (error) {
      toast(`已加入白名单，但打包失败：${error.message}`, true);
    }
  } catch (error) {
    toast(error.message, true);
  }
});

// ── 版本发布 ──

function sizeText(bytes) {
  if (!bytes) return '0 MB';
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function refreshReleases() {
  const rows = await api.releases.list();
  const body = document.getElementById('releases-body');
  body.replaceChildren();
  rows.forEach((release) => {
    const tr = document.createElement('tr');
    const version = document.createElement('td');
    version.textContent = release.version;
    const note = document.createElement('div');
    note.className = 'hint';
    note.textContent = release.changelog;
    version.append(note);

    tr.append(version, cell(release.file_count), cell(sizeText(release.total_size)));
    tr.append(cell(release.mandatory ? '强制' : '可选'));
    tr.append(cell(release.enabled ? '生效中' : '未启用'));

    const actions = document.createElement('td');
    if (!release.enabled) {
      const publish = document.createElement('button');
      publish.className = 'link';
      publish.textContent = '发布';
      publish.addEventListener('click', async () => {
        await api.releases.publish(release.version);
        toast(`${release.version} 已生效`);
        await refreshReleases();
      });
      actions.append(publish);
    }
    const mandatory = document.createElement('button');
    mandatory.className = 'link';
    mandatory.textContent = release.mandatory ? '取消强制' : '设为强制';
    mandatory.addEventListener('click', async () => {
      await api.releases.patch(release.version, { mandatory: !release.mandatory });
      await refreshReleases();
    });
    const drop = document.createElement('button');
    drop.className = 'link danger';
    drop.textContent = '删除';
    drop.addEventListener('click', async () => {
      if (!confirm(`确认删除版本 ${release.version}？`)) return;
      await api.releases.remove(release.version);
      await refreshReleases();
    });
    actions.append(mandatory, drop);
    tr.append(actions);
    body.append(tr);
  });
}

document.getElementById('release-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  form.set('mandatory', form.get('mandatory') === 'on' ? 'true' : 'false');
  try {
    await api.releases.upload(form);
    event.target.reset();
    toast('上传完成，记得点"发布"才会生效');
    await refreshReleases();
  } catch (error) {
    toast(error.message, true);
  }
});

// ── 握手日志 ──

async function refreshLogs() {
  const rows = await api.logs.list(200);
  const body = document.getElementById('logs-body');
  body.replaceChildren();
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    tr.append(
      cell(row.created_at), cell(row.player_id), cell(row.player_name || '—'),
      cell(row.bound_player_id), cell(row.guild), cell(row.client_version), cell(row.remote),
    );
    const result = document.createElement('td');
    result.textContent = row.allowed ? '放行' : `拒绝（${row.reason}）`;
    result.className = row.allowed ? 'ok' : 'bad';
    tr.append(result);
    body.append(tr);
  });
}

// ── 启动 ──

if (api.token()) {
  document.getElementById('who').textContent = '已登录';
  show('players');
  refreshPlayers().catch(() => show('login'));
} else {
  show('login');
}
