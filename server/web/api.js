/** 管理端 API 封装：统一带 JWT，统一抛错。 */

const TOKEN_KEY = 'e0e1_admin_token';

export function token() {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setToken(value) {
  if (value) localStorage.setItem(TOKEN_KEY, value);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (token()) headers.set('Authorization', `Bearer ${token()}`);
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch (error) {
    throw new Error(`无法连接服务器：${error.message}`);
  }
  if (response.status === 401) {
    setToken('');
    location.reload();
    throw new Error('登录已过期');
  }
  if (!response.ok) {
    const detail = await response.text();
    let message = detail;
    try {
      message = JSON.parse(detail).detail || detail;
    } catch { /* 非 JSON 就用原文 */ }
    throw new Error(message || `请求失败（${response.status}）`);
  }
  if (response.status === 204) return null;
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response.text();
}

export function login(username, password) {
  return request('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
}

export const players = {
  list: () => request('/api/players'),
  create: (payload) => request('/api/players', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  patch: (playerId, payload) => request(`/api/players/${encodeURIComponent(playerId)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  remove: (playerId) => request(`/api/players/${encodeURIComponent(playerId)}`, { method: 'DELETE' }),
  issueLicense: (playerId) => request(`/api/players/${encodeURIComponent(playerId)}/license`, { method: 'POST' }),

  /** 下载完整分发包：体积大，走 blob 再触发保存，避免把 token 拼在 URL 上。 */
  async downloadPackage(playerId) {
    const multiple = Array.isArray(playerId);
    const response = await fetch(multiple ? '/api/players/package' : `/api/players/${encodeURIComponent(playerId)}/package`, {
      method: multiple ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${token()}`, ...(multiple ? {'Content-Type': 'application/json'} : {}) },
      ...(multiple ? {body: JSON.stringify({player_ids: playerId})} : {}),
    });
    if (!response.ok) {
      const raw = await response.text();
      let message = raw;
      try {
        message = JSON.parse(raw).detail || raw;
      } catch { /* 非 JSON 就用原文 */ }
      throw new Error(message || `打包失败（${response.status}）`);
    }
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = Array.isArray(playerId) ? `e0e1-wx-plugins-${playerId.length}players.zip` : `e0e1-wx-plugins-${playerId}.zip`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  },
};

export const releases = {
  list: () => request('/api/releases'),
  upload: (form) => request('/api/releases/upload', { method: 'POST', body: form }),
  publish: (version) => request(`/api/releases/${encodeURIComponent(version)}/publish`, { method: 'POST' }),
  patch: (version, payload) => request(`/api/releases/${encodeURIComponent(version)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  remove: (version) => request(`/api/releases/${encodeURIComponent(version)}`, { method: 'DELETE' }),
};

export const logs = {
  list: (limit = 200) => request(`/api/logs?limit=${limit}`),
};
