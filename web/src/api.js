const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:3000'

async function request(path, options = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
    },
    ...options,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const message = data.message || res.statusText
    throw new Error(message)
  }
  return res.json()
}

export async function apiLoginTelegram(payload) {
  return request('/auth/telegram', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function apiGetMe(token) {
  return request('/auth/me', { token })
}

export async function apiGetMonthEvents(token, year, month) {
  return request(`/events/month?year=${year}&month=${month}`, { token })
}

export async function apiGetDayEvents(token, year, month, day) {
  return request(`/events/day?year=${year}&month=${month}&day=${day}`, { token })
}

export async function apiCreateEvent(token, payload) {
  return request('/events', {
    method: 'POST',
    token,
    body: JSON.stringify(payload),
  })
}

export async function apiDeleteEvent(token, id, date) {
  const suffix = date ? `?date=${date}` : ''
  return request(`/events/${id}${suffix}`, {
    method: 'DELETE',
    token,
  })
}

export async function apiGetParticipants(token) {
  return request('/participants', { token })
}

export async function apiDeleteParticipants(token, tgIds) {
  return request('/participants', {
    method: 'DELETE',
    token,
    body: JSON.stringify({ tg_ids: tgIds }),
  })
}
