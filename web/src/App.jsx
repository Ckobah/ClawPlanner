import { useEffect, useMemo, useState } from 'react'
import './App.css'
import {
  apiDeleteParticipants,
  apiDeleteEvent,
  apiGetDayEvents,
  apiGetMe,
  apiGetMonthEvents,
  apiGetParticipants,
  apiLoginTelegram,
  apiCreateEvent,
} from './api'
import { TelegramLoginButton } from './telegram'

const RECURRENCE_LABELS = {
  never: 'Никогда',
  daily: 'Ежедневно',
  weekly: 'Еженедельно',
  monthly: 'Ежемесячно',
  annual: 'Ежегодно',
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('auth_token') || '')
  const [user, setUser] = useState(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [viewDate, setViewDate] = useState(() => new Date())
  const [selectedDate, setSelectedDate] = useState(() => new Date())
  const [monthData, setMonthData] = useState({})
  const [dayEvents, setDayEvents] = useState([])
  const [participants, setParticipants] = useState([])
  const [selectedParticipants, setSelectedParticipants] = useState([])
  const [tab, setTab] = useState('event')

  const [form, setForm] = useState({
    date: '',
    start_time: '12:00',
    stop_time: '',
    description: '',
    recurrent: 'never',
    participants: [],
  })

  const monthLabel = useMemo(() => {
    return viewDate.toLocaleString('ru-RU', { month: 'long', year: 'numeric' })
  }, [viewDate])

  useEffect(() => {
    if (!token) return
    setLoading(true)
    apiGetMe(token)
      .then((data) => {
        setUser(data.user)
        setIsAdmin(data.is_admin)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => {
    if (!token) return
    const year = viewDate.getFullYear()
    const month = viewDate.getMonth() + 1
    apiGetMonthEvents(token, year, month)
      .then((data) => setMonthData(data.days || {}))
      .catch((err) => setError(err.message))
  }, [token, viewDate])

  useEffect(() => {
    if (!token || !selectedDate) return
    const year = selectedDate.getFullYear()
    const month = selectedDate.getMonth() + 1
    const day = selectedDate.getDate()
    apiGetDayEvents(token, year, month, day)
      .then((data) => setDayEvents(data))
      .catch((err) => setError(err.message))
  }, [token, selectedDate])

  useEffect(() => {
    if (!token) return
    apiGetParticipants(token)
      .then((data) => setParticipants(data))
      .catch((err) => setError(err.message))
  }, [token])

  useEffect(() => {
    if (!selectedDate) return
    const date = selectedDate.toISOString().slice(0, 10)
    setForm((prev) => ({ ...prev, date }))
  }, [selectedDate])

  const calendarCells = useMemo(() => {
    const year = viewDate.getFullYear()
    const month = viewDate.getMonth()
    const firstDay = new Date(year, month, 1)
    const startOffset = (firstDay.getDay() + 6) % 7
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const cells = []

    for (let i = 0; i < startOffset; i += 1) {
      cells.push(null)
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
      cells.push(new Date(year, month, day))
    }
    while (cells.length < 42) {
      cells.push(null)
    }
    return cells
  }, [viewDate])

  const handleTelegramAuth = async (tgUser) => {
    setError('')
    setLoading(true)
    try {
      const data = await apiLoginTelegram(tgUser)
      localStorage.setItem('auth_token', data.token)
      setToken(data.token)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleCreateEvent = async (event) => {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      await apiCreateEvent(token, {
        ...form,
        participants: form.participants,
      })
      const year = selectedDate.getFullYear()
      const month = selectedDate.getMonth() + 1
      const day = selectedDate.getDate()
      const [monthRes, dayRes] = await Promise.all([
        apiGetMonthEvents(token, year, month),
        apiGetDayEvents(token, year, month, day),
      ])
      setMonthData(monthRes.days || {})
      setDayEvents(dayRes)
      setForm((prev) => ({ ...prev, description: '', participants: [] }))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteEvent = async (eventId, singleEvent) => {
    setError('')
    setLoading(true)
    try {
      const date = singleEvent ? null : selectedDate.toISOString().slice(0, 10)
      await apiDeleteEvent(token, eventId, date)
      const year = selectedDate.getFullYear()
      const month = selectedDate.getMonth() + 1
      const day = selectedDate.getDate()
      const [monthRes, dayRes] = await Promise.all([
        apiGetMonthEvents(token, year, month),
        apiGetDayEvents(token, year, month, day),
      ])
      setMonthData(monthRes.days || {})
      setDayEvents(dayRes)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteParticipants = async () => {
    if (!selectedParticipants.length) return
    setLoading(true)
    setError('')
    try {
      await apiDeleteParticipants(token, selectedParticipants)
      const updated = await apiGetParticipants(token)
      setParticipants(updated)
      setSelectedParticipants([])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (!token) {
    return (
      <div className="app">
        <div className="board hero-board">
          <header className="hero">
            <div>
              <p className="eyebrow">Семейный планировщик</p>
              <h1>Планируйте события и напоминания</h1>
              <p className="lead">
                Вход через Telegram, управление событиями, участниками и напоминаниями.
              </p>
            </div>
            <div className="login-card">
              <h2>Вход</h2>
              <p>Войдите через Telegram, чтобы продолжить.</p>
              <TelegramLoginButton onAuth={handleTelegramAuth} />
              {error && <div className="error">{error}</div>}
            </div>
          </header>
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <div className="board">
        <header className="topbar">
          <div>
            <h1>Семейный планировщик</h1>
            <p>Добро пожаловать, {user?.firstName || user?.username || 'пользователь'}</p>
          </div>
          <div className="top-actions">
            <button
              className={tab === 'event' ? 'tab active' : 'tab'}
              onClick={() => setTab('event')}
            >
              События
            </button>
            <button
              className={tab === 'team' ? 'tab active' : 'tab'}
              onClick={() => setTab('team')}
            >
              Участники
            </button>
            {isAdmin && <span className="badge">Админ</span>}
          </div>
        </header>

        <section className="layout">
          <div className="calendar">
            <div className="calendar-header">
              <button onClick={() => setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1))}>
                {'<'}
              </button>
              <h2>{monthLabel}</h2>
              <button onClick={() => setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1))}>
                {'>'}
              </button>
            </div>
            <div className="calendar-grid">
              {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((day) => (
                <div key={day} className="calendar-weekday">
                  {day}
                </div>
              ))}
              {calendarCells.map((date, idx) => {
                if (!date) {
                  return <div key={`empty-${idx}`} className="calendar-cell empty" />
                }
                const day = date.getDate()
                const count = monthData[day] || 0
                const isSelected =
                  selectedDate && date.toDateString() === selectedDate.toDateString()
                return (
                  <button
                    key={date.toISOString()}
                    className={`calendar-cell ${isSelected ? 'selected' : ''}`}
                    onClick={() => setSelectedDate(date)}
                  >
                    <span>{day}</span>
                    {count > 0 && <span className="count">{count}</span>}
                  </button>
                )
              })}
            </div>
            <div className="day-events">
              <h3>События на {selectedDate.toLocaleDateString('ru-RU')}</h3>
              {dayEvents.length === 0 && <p>Событий нет.</p>}
              {dayEvents.map((event) => (
                <div key={event.id} className="event-card">
                  <div>
                    <strong>{event.start_time}</strong>
                    {event.stop_time ? ` - ${event.stop_time}` : ''}
                    <p>{event.description}</p>
                    {event.recurrent && event.recurrent !== 'never' && (
                      <span className="tag">{RECURRENCE_LABELS[event.recurrent]}</span>
                    )}
                  </div>
                  <button onClick={() => handleDeleteEvent(event.id, event.single_event)}>Удалить</button>
                </div>
              ))}
            </div>
          </div>

          <aside className="panel">
            {tab === 'event' && (
              <form className="event-form" onSubmit={handleCreateEvent}>
                <h3>Новое событие</h3>
                <label>
                  Дата
                  <input
                    type="date"
                    value={form.date}
                    onChange={(e) => setForm({ ...form, date: e.target.value })}
                  />
                </label>
                <label>
                  Начало
                  <input
                    type="time"
                    value={form.start_time}
                    onChange={(e) => setForm({ ...form, start_time: e.target.value })}
                  />
                </label>
                <label>
                  Окончание
                  <input
                    type="time"
                    value={form.stop_time}
                    onChange={(e) => setForm({ ...form, stop_time: e.target.value })}
                  />
                </label>
                <label>
                  Описание
                  <textarea
                    rows="3"
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                  />
                </label>
                <label>
                  Повтор
                  <select
                    value={form.recurrent}
                    onChange={(e) => setForm({ ...form, recurrent: e.target.value })}
                  >
                    {Object.entries(RECURRENCE_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="participants">
                  <p>Участники</p>
                  {participants.length === 0 && <span>Нет доступных участников.</span>}
                  {participants.map((p) => (
                    <label key={p.tg_id} className={p.is_active ? '' : 'muted'}>
                      <input
                        type="checkbox"
                        checked={form.participants.includes(p.tg_id)}
                        disabled={!p.is_active}
                        onChange={(e) => {
                          const next = e.target.checked
                            ? [...form.participants, p.tg_id]
                            : form.participants.filter((id) => id !== p.tg_id)
                          setForm({ ...form, participants: next })
                        }}
                      />
                      {p.first_name || p.tg_id} {!p.is_active && '(не в боте)'}
                    </label>
                  ))}
                </div>
                <button type="submit" disabled={!form.description}>
                  Создать событие
                </button>
              </form>
            )}

            {tab === 'team' && (
              <div className="team-panel">
                <h3>Управление участниками</h3>
                {participants.length === 0 && <p>Нет участников.</p>}
                {participants.map((p) => (
                  <label key={p.tg_id} className="team-item">
                    <input
                      type="checkbox"
                      checked={selectedParticipants.includes(p.tg_id)}
                      onChange={(e) => {
                        const next = e.target.checked
                          ? [...selectedParticipants, p.tg_id]
                          : selectedParticipants.filter((id) => id !== p.tg_id)
                        setSelectedParticipants(next)
                      }}
                    />
                    <span>{p.first_name || p.tg_id}</span>
                    {!p.is_active && <em>не в боте</em>}
                  </label>
                ))}
                <button onClick={handleDeleteParticipants} disabled={!selectedParticipants.length}>
                  Удалить участников
                </button>
              </div>
            )}

            {loading && <div className="loading">Загрузка...</div>}
            {error && <div className="error">{error}</div>}
          </aside>
        </section>
      </div>
    </div>
  )
}

export default App
