import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, ArrowRight, CheckCircle2, Database, Globe2, Loader2, Mic, Search, Sparkles, Video, X } from 'lucide-react'
import { supabase } from './lib/supabase'
import { getRecordingDetails, listRecordings } from './lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { StartRecordingDialog } from '@/components/StartRecordingDialog'

const OFFLINE_PLATFORMS = new Set(['offline', 'local'])
const SMART_SEARCH_STOP_WORDS = new Set([
  'show', 'me', 'meeting', 'meetings', 'where', 'was', 'were', 'is', 'are', 'the', 'a', 'an',
  'discussed', 'about', 'that', 'with', 'which', 'find', 'all', 'please', 'in', 'to', 'for',
])

function tokenizeNaturalQuery(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .map((token) => token.trim())
    .filter(Boolean)
}

function getSearchIntent(rawQuery) {
  const normalized = (rawQuery || '').trim().toLowerCase()

  const intent = {
    raw: normalized,
    tokens: [],
    scope: null,
    status: null,
    dateRange: null,
  }

  if (!normalized) return intent

  if (/\bonline\b/.test(normalized)) intent.scope = 'online'
  if (/\boffline\b/.test(normalized)) intent.scope = 'offline'

  if (/\brecording\b|\blive\b|\bin progress\b/.test(normalized)) intent.status = 'recording'
  if (/\bcompleted\b|\bdone\b|\bfinished\b/.test(normalized)) intent.status = 'completed'

  if (/\btoday\b/.test(normalized)) intent.dateRange = 'today'
  if (/\bthis week\b|\bweek\b/.test(normalized)) intent.dateRange = 'week'

  const quotedPhrases = [...normalized.matchAll(/"([^"]+)"/g)]
    .map((match) => match[1].trim())
    .filter(Boolean)

  let tokenSource = normalized.replace(/"[^"]+"/g, ' ')
  const whereMatch = normalized.match(/\bwhere\b(.+?)(?:\bwas\b|\bwere\b|\bis\b|\bin\b|$)/)
  if (whereMatch?.[1]) {
    tokenSource += ` ${whereMatch[1]}`
  }

  const looseTokens = tokenizeNaturalQuery(tokenSource).filter((token) => !SMART_SEARCH_STOP_WORDS.has(token))
  intent.tokens = [...new Set([...quotedPhrases, ...looseTokens])]
  return intent
}

function isWithinDateRange(dateValue, dateRange) {
  if (!dateRange) return true

  const current = new Date()
  const createdAt = new Date(dateValue)
  if (Number.isNaN(createdAt.getTime())) return false

  if (dateRange === 'today') {
    return createdAt.toDateString() === current.toDateString()
  }

  if (dateRange === 'week') {
    const sevenDaysMs = 7 * 24 * 60 * 60 * 1000
    return current.getTime() - createdAt.getTime() <= sevenDaysMs
  }

  return true
}

function matchesSmartSearch(meeting, intent) {
  if (!intent.raw) return true

  const platform = (meeting.platform || '').toLowerCase()
  const status = (meeting.status || '').toLowerCase()
  const isOffline = OFFLINE_PLATFORMS.has(platform)

  if (intent.scope === 'online' && isOffline) return false
  if (intent.scope === 'offline' && !isOffline) return false
  if (intent.status && status !== intent.status) return false
  if (!isWithinDateRange(meeting.createdAt, intent.dateRange)) return false

  if (!intent.tokens.length) return true

  const haystack = [
    meeting.title,
    meeting.summary,
    meeting.language,
    meeting.platform,
    meeting.status,
  ]
    .join(' ')
    .toLowerCase()

  return intent.tokens.every((token) => haystack.includes(token))
}

function inferMeetingPlatform(row) {
  const normalizedPlatform = (row?.platform || '').toString().trim().toLowerCase()
  if (normalizedPlatform) return normalizedPlatform

  const summaryText = (row?.summary || '').toString().toLowerCase()
  if (
    summaryText.includes('offline meeting details:') ||
    summaryText.includes('offline meeting was added manually')
  ) {
    return 'offline'
  }

  return 'meet'
}

function normalizeMeeting(row) {
  return {
    id: row.id,
    title: row.title || 'Untitled Meeting',
    platform: inferMeetingPlatform(row),
    status: row.status || 'completed',
    language: row.language || 'Auto',
    summary: row.summary || '',
    createdAt: row.created_at || new Date().toISOString(),
  }
}

function sortMeetings(items) {
  return [...items].sort((left, right) => new Date(right.createdAt) - new Date(left.createdAt))
}

function formatDate(value) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'Unknown date'
  return parsed.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function parseBackendTranscript(transcriptText) {
  const lines = (transcriptText || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

  return lines.map((line, index) => {
    const parsed = line.match(/^\[(\d{2}):(\d{2}):(\d{2})\s*-\s*[^\]]+\]\s*(.*?):\s*(.*)$/)
    if (parsed) {
      const hours = Number(parsed[1]) || 0
      const minutes = Number(parsed[2]) || 0
      const seconds = Number(parsed[3]) || 0
      return {
        id: `api-line-${index}`,
        speaker_name: parsed[4] || 'Participant',
        spoken_text: parsed[5] || '',
        start_time_seconds: hours * 3600 + minutes * 60 + seconds,
      }
    }

    return {
      id: `api-line-${index}`,
      speaker_name: 'Participant',
      spoken_text: line,
      start_time_seconds: index * 15,
    }
  })
}

function HeroPage({ hasSession, onEnter }) {
  const storySteps = [
    {
      title: 'Schedule Meeting',
      description: 'Create an online session or log an offline discussion in seconds.',
    },
    {
      title: 'Capture Conversations',
      description: 'The assistant joins online calls and streams transcript updates in real time.',
    },
    {
      title: 'Ship Decisions',
      description: 'Generate concise summaries, action items, and searchable notes instantly.',
    },
  ]

  return (
    <div className="relative min-h-screen overflow-hidden bg-[linear-gradient(145deg,#fff8ef_0%,#eff7ff_45%,#e8f7f2_100%)] text-slate-900">
      <div className="pointer-events-none absolute -left-16 -top-16 h-72 w-72 rounded-full bg-orange-300/30 blur-3xl" />
      <div className="pointer-events-none absolute bottom-0 right-0 h-80 w-80 rounded-full bg-sky-300/30 blur-3xl" />

      <div className="relative mx-auto grid min-h-screen w-full max-w-[1400px] gap-8 px-6 py-10 md:grid-cols-[1.1fr_0.9fr] md:items-center md:px-10">
        <section>
          <p className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-white/75 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-sky-700">
            <Sparkles className="h-3.5 w-3.5" />
            OceanLabs Smart Meeting Notes
          </p>

          <h1 className="mt-5 max-w-3xl text-4xl font-semibold leading-tight text-slate-900 md:text-6xl">
            AI Meeting Intelligence For
            <span className="block bg-gradient-to-r from-sky-700 via-cyan-600 to-indigo-700 bg-clip-text text-transparent">
              Modern Product Teams
            </span>
          </h1>

          <p className="mt-5 max-w-2xl text-base leading-relaxed text-slate-600 md:text-lg">
            Turn every meeting into clear outcomes. Capture conversations across Google Meet, Teams, Zoom, and offline discussions, then generate structured notes your team can search and reuse.
          </p>

          <div className="mt-7 flex flex-wrap gap-3">
            <Button onClick={onEnter} className="h-11 bg-sky-600 px-6 font-semibold text-white hover:bg-sky-500">
              {hasSession ? 'Enter Dashboard' : 'Get Started'}
            </Button>
            <div className="inline-flex h-11 items-center rounded-lg border border-slate-200 bg-white/80 px-4 text-sm font-medium text-slate-600">
              Live capture, searchable notes, action-ready summaries
            </div>
          </div>

          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            <article className="rounded-xl border border-slate-200 bg-white/80 p-4 shadow-sm">
              <p className="mb-1 inline-flex items-center gap-2 text-sm font-semibold text-sky-700">
                <Globe2 className="h-4 w-4" />
                Automated Online Capture
              </p>
              <p className="text-sm text-slate-600">Start from one link and track transcript updates while the assistant captures the session.</p>
            </article>
            <article className="rounded-xl border border-slate-200 bg-white/80 p-4 shadow-sm">
              <p className="mb-1 inline-flex items-center gap-2 text-sm font-semibold text-sky-700">
                <Database className="h-4 w-4" />
                Secure Team Workspace
              </p>
              <p className="text-sm text-slate-600">Meetings, transcript lines, and summaries stay organized in one private workspace.</p>
            </article>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white/85 p-5 shadow-sm backdrop-blur md:p-6">
          <p className="text-sm font-semibold text-sky-700">How It Works</p>
          <p className="mt-1 text-sm text-slate-600">Schedule - Capture - Summarize</p>
          <div className="mt-4 grid gap-3">
            {storySteps.map((step, index) => (
              <article
                key={step.title}
                className="hero-story-step"
                style={{ '--story-delay': `${index * 130}ms` }}
              >
                <div className="hero-story-step-body rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-sky-600 px-1.5 text-[11px] font-semibold text-white">
                      {index + 1}
                    </span>
                    <h3 className="text-sm font-semibold text-slate-800">{step.title}</h3>
                    {index < storySteps.length - 1 ? (
                      <ArrowRight className="h-3.5 w-3.5 text-slate-400" />
                    ) : null}
                  </div>
                  <p className="text-sm text-slate-600">{step.description}</p>
                </div>
              </article>
            ))}
          </div>

          <div className="mt-5 rounded-xl border border-sky-200 bg-sky-50 px-3 py-2.5 text-xs text-sky-700">
            Built for global teams: use Auto mode or set a preferred language for transcription and summaries.
          </div>
        </section>
      </div>
    </div>
  )
}

function AuthScreen() {
  const [mode, setMode] = useState('login')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const handleSubmit = async (event) => {
    event.preventDefault()
    setLoading(true)
    setError('')
    setNotice('')

    try {
      if (mode === 'login') {
        const { error: signInError } = await supabase.auth.signInWithPassword({ email, password })
        if (signInError) throw signInError
      } else {
        const { error: signUpError } = await supabase.auth.signUp({
          email,
          password,
          options: {
            data: {
              full_name: fullName.trim(),
            },
          },
        })
        if (signUpError) throw signUpError

        setNotice('Account created. If email confirmation is enabled, verify your email before login.')
        setMode('login')
      }
    } catch (authError) {
      setError(authError?.message || 'Authentication failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_10%_10%,_#e0e7ff_0%,_#f8fafc_45%,_#eef2ff_100%)] px-4 py-10">
      <div className="w-full max-w-[460px] rounded-2xl border border-neutral-200 bg-white/95 p-7 shadow-xl shadow-indigo-100/70 backdrop-blur">
        <div className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-600">OceanLabs</p>
          <h1 className="mt-1 text-2xl font-semibold text-neutral-900">Smart Meeting Notes</h1>
          <p className="mt-2 text-sm text-neutral-600">
            Sign in to your workspace to manage recordings, transcripts, and action-ready meeting notes.
          </p>
        </div>

        <div className="mb-5 flex gap-2 rounded-xl bg-neutral-100 p-1">
          <button
            type="button"
            onClick={() => setMode('login')}
            className={`h-9 flex-1 rounded-lg text-sm font-semibold transition ${
              mode === 'login' ? 'bg-white text-neutral-900 shadow-sm' : 'text-neutral-500'
            }`}
          >
            Login
          </button>
          <button
            type="button"
            onClick={() => setMode('signup')}
            className={`h-9 flex-1 rounded-lg text-sm font-semibold transition ${
              mode === 'signup' ? 'bg-white text-neutral-900 shadow-sm' : 'text-neutral-500'
            }`}
          >
            Sign Up
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'signup' ? (
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Full Name</label>
              <Input
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                placeholder="Your name"
                className="h-10 border-neutral-200 bg-neutral-50"
                required
              />
            </div>
          ) : null}

          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Email</label>
            <Input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@company.com"
              className="h-10 border-neutral-200 bg-neutral-50"
              required
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Password</label>
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter password"
              className="h-10 border-neutral-200 bg-neutral-50"
              required
              minLength={6}
            />
          </div>

          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
          ) : null}

          {notice ? (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div>
          ) : null}

          <Button type="submit" disabled={loading} className="h-10 w-full bg-indigo-600 font-semibold text-white hover:bg-indigo-500">
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Please wait...
              </>
            ) : mode === 'login' ? (
              'Login'
            ) : (
              'Create Account'
            )}
          </Button>
        </form>
      </div>
    </div>
  )
}

function MeetingGrid({ meetings, onOpenMeeting, emptyMessage }) {
  if (!meetings.length) {
    return (
      <div className="rounded-2xl border border-dashed border-neutral-300 bg-neutral-50 px-6 py-12 text-center text-sm text-neutral-500">
        {emptyMessage}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      {meetings.map((meeting) => (
        <article
          key={meeting.id}
          className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm transition hover:shadow-md"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-neutral-900">{meeting.title}</h3>
            <span className="rounded-full bg-neutral-100 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-600">
              {meeting.platform}
            </span>
          </div>

          <p className="mt-1 text-xs text-neutral-500">{formatDate(meeting.createdAt)}</p>

          <div className="mt-3 flex flex-wrap gap-2">
            <span className="rounded-md bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700">{meeting.language}</span>
            <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700">{meeting.status}</span>
          </div>

          <p className="mt-3 line-clamp-2 text-sm text-neutral-600">
            {meeting.summary || 'No summary yet. Open notes to see transcript segments and updates.'}
          </p>

          <div className="mt-4 flex justify-end">
            <Button variant="outline" size="sm" onClick={() => onOpenMeeting(meeting)} className="border-neutral-300">
              Open Notes
            </Button>
          </div>
        </article>
      ))}
    </div>
  )
}

function MeetingNotesPanel({ meeting, transcripts, loading, onClose }) {
  if (!meeting) return null

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-[420px] border-l border-neutral-200 bg-white shadow-2xl">
      <div className="flex h-full flex-col">
        <header className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-neutral-900">{meeting.title}</p>
            <p className="text-xs text-neutral-500">{meeting.platform} - {meeting.language}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-neutral-500 transition hover:bg-neutral-100 hover:text-neutral-700"
            aria-label="Close notes"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {meeting.summary ? (
          <section className="border-b border-neutral-200 bg-indigo-50/70 px-4 py-3">
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-indigo-700">Summary</p>
            <p className="text-sm leading-relaxed text-neutral-700">{meeting.summary}</p>
          </section>
        ) : null}

        <section className="flex-1 overflow-y-auto px-4 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-neutral-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading transcript...
            </div>
          ) : transcripts.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-neutral-300 bg-neutral-50 px-4 py-10 text-center">
              <Activity className="h-6 w-6 text-neutral-400" />
              <p className="text-sm font-medium text-neutral-600">No transcript lines yet</p>
              <p className="text-xs text-neutral-500">
                For online meetings, the bot starts adding lines once it joins and starts recording.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {transcripts.map((line, index) => {
                const timeLabel = Number.isFinite(line.start_time_seconds)
                  ? new Date(line.start_time_seconds * 1000).toISOString().slice(14, 19)
                  : '--:--'

                return (
                  <article key={line.id || `${line.speaker_name}-${index}`} className="rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2.5">
                    <p className="mb-1 text-[11px] font-semibold text-neutral-500">
                      {line.speaker_name || 'Participant'} - {timeLabel}
                    </p>
                    <p className="text-sm leading-relaxed text-neutral-700">{line.spoken_text}</p>
                  </article>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function SettingsView({ session, onUpdatedProfile }) {
  const [displayName, setDisplayName] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    setDisplayName(session?.user?.user_metadata?.full_name || '')
  }, [session?.user?.user_metadata?.full_name])

  const handleSaveProfile = async () => {
    setSaving(true)
    setError('')
    setMessage('')

    const { error: updateError } = await supabase.auth.updateUser({
      data: {
        full_name: displayName.trim(),
      },
    })

    if (updateError) {
      setError(updateError.message)
    } else {
      setMessage('Profile updated successfully.')
      onUpdatedProfile?.()
    }

    setSaving(false)
  }

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-neutral-900">Personal Settings</h2>
        <p className="mt-1 text-sm text-neutral-600">Manage your profile details and bot behavior preferences.</p>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Full Name</label>
            <Input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              className="h-10 border-neutral-200 bg-neutral-50"
              placeholder="Your name"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Email</label>
            <Input value={session?.user?.email || ''} disabled className="h-10 border-neutral-200 bg-neutral-100" />
          </div>
        </div>

        <div className="mt-5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs text-indigo-700">
          Meeting assistant is enabled for online meeting capture.
        </div>

        {message ? (
          <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{message}</div>
        ) : null}

        {error ? (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        ) : null}

        <div className="mt-4 flex justify-end">
          <Button onClick={handleSaveProfile} disabled={saving} className="h-10 bg-indigo-600 font-semibold text-white hover:bg-indigo-500">
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Saving
              </>
            ) : (
              'Save Settings'
            )}
          </Button>
        </div>
      </section>
    </div>
  )
}

export default function App() {
  const [showHero, setShowHero] = useState(true)
  const [session, setSession] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [activeSection, setActiveSection] = useState('dashboard')
  const [activeDashboardTab, setActiveDashboardTab] = useState('overview')
  const [meetings, setMeetings] = useState([])
  const [recordingSessions, setRecordingSessions] = useState([])
  const [meetingsLoading, setMeetingsLoading] = useState(true)
  const [meetingsError, setMeetingsError] = useState('')
  const [activeRecordings, setActiveRecordings] = useState(0)
  const [selectedMeeting, setSelectedMeeting] = useState(null)
  const [transcripts, setTranscripts] = useState([])
  const [transcriptsLoading, setTranscriptsLoading] = useState(false)
  const [toastMessage, setToastMessage] = useState('')
  const [smartSearchQuery, setSmartSearchQuery] = useState('')

  const loadMeetings = useCallback(async () => {
    setMeetingsLoading(true)
    setMeetingsError('')

    const { data, error } = await supabase
      .from('meetings')
      .select('*')
      .order('created_at', { ascending: false })

    if (error) {
      setMeetingsError('Unable to load meetings from Supabase. Please verify table permissions.')
      setMeetings([])
      setMeetingsLoading(false)
      return
    }

    setMeetings(sortMeetings((data || []).map(normalizeMeeting)))
    setMeetingsLoading(false)
  }, [])

  useEffect(() => {
    let mounted = true

    supabase.auth.getSession().then(({ data }) => {
      if (!mounted) return
      setSession(data.session)
      setAuthLoading(false)
    })

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession)
      setAuthLoading(false)
    })

    return () => {
      mounted = false
      subscription.unsubscribe()
    }
  }, [])

  useEffect(() => {
    if (!session) {
      setMeetings([])
      setSelectedMeeting(null)
      return
    }

    loadMeetings()

    const channel = supabase
      .channel(`meetings-feed-${session.user.id}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'meetings' }, (payload) => {
        if (payload.eventType === 'DELETE' && payload.old?.id) {
          setMeetings((prev) => prev.filter((item) => item.id !== payload.old.id))
          setSelectedMeeting((prev) => (prev?.id === payload.old.id ? null : prev))
          return
        }

        if (!payload.new) return

        const updated = normalizeMeeting(payload.new)
        setMeetings((prev) => {
          const existing = prev.find((item) => item.id === updated.id)
          if (!existing) return sortMeetings([updated, ...prev])
          return sortMeetings(prev.map((item) => (item.id === updated.id ? updated : item)))
        })
        setSelectedMeeting((prev) => (prev?.id === updated.id ? updated : prev))
      })
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [session, loadMeetings])

  useEffect(() => {
    if (!session) {
      setActiveRecordings(0)
      setRecordingSessions([])
      return
    }

    let active = true

    const syncRecordings = async () => {
      try {
        const data = await listRecordings()
        if (!active) return
        const sessions = data || []
        const running = sessions.filter((entry) => entry.status === 'recording').length
        setRecordingSessions(sessions)
        setActiveRecordings(running)
      } catch {
        if (active) {
          setRecordingSessions([])
          setActiveRecordings(0)
        }
      }
    }

    syncRecordings()
    const timer = setInterval(syncRecordings, 6000)

    return () => {
      active = false
      clearInterval(timer)
    }
  }, [session])

  useEffect(() => {
    if (!selectedMeeting) {
      setTranscripts([])
      return
    }

    let active = true
    setTranscriptsLoading(true)

    if (selectedMeeting.id?.startsWith('api-')) {
      const recordingId = selectedMeeting.recordingId || selectedMeeting.id.slice(4)

      getRecordingDetails(recordingId)
        .then((detail) => {
          if (!active) return
          setTranscripts(parseBackendTranscript(detail?.transcript || ''))
        })
        .catch(() => {
          if (!active) return
          setTranscripts([])
        })
        .finally(() => {
          if (active) setTranscriptsLoading(false)
        })

      return () => {
        active = false
      }
    }

    supabase
      .from('transcripts')
      .select('*')
      .eq('meeting_id', selectedMeeting.id)
      .order('start_time_seconds', { ascending: true })
      .then(({ data }) => {
        if (!active) return
        setTranscripts(data || [])
        setTranscriptsLoading(false)
      })

    const channel = supabase
      .channel(`transcript-feed-${selectedMeeting.id}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'transcripts',
          filter: `meeting_id=eq.${selectedMeeting.id}`,
        },
        (payload) => {
          setTranscripts((prev) => [...prev, payload.new])
        }
      )
      .subscribe()

    return () => {
      active = false
      supabase.removeChannel(channel)
    }
  }, [selectedMeeting])

  useEffect(() => {
    if (!toastMessage) return undefined
    const timer = setTimeout(() => setToastMessage(''), 4200)
    return () => clearTimeout(timer)
  }, [toastMessage])

  const searchIntent = useMemo(() => getSearchIntent(smartSearchQuery), [smartSearchQuery])

  const apiDerivedMeetings = useMemo(() => {
    return recordingSessions.map((entry) => {
      const createdAt = entry?.created_at
        ? new Date(entry.created_at * 1000).toISOString()
        : new Date().toISOString()

      const baseSummary =
        entry?.status === 'recording'
          ? 'Recording is in progress from backend session.'
          : entry?.status === 'error'
            ? `Recording session failed: ${entry?.error || 'Unknown error'}`
            : 'Recording session completed in backend runtime.'

      return {
        id: `api-${entry.id}`,
        recordingId: entry.id,
        title: entry?.title || 'Untitled Meeting',
        platform: entry?.platform || 'meet',
        status: entry?.status || 'recording',
        language: entry?.language || 'Auto',
        summary: entry?.summary || baseSummary,
        createdAt,
      }
    })
  }, [recordingSessions])

  const allMeetings = useMemo(() => {
    const existingKeys = new Set(
      meetings
        .filter((item) => (item.status || '').toLowerCase() === 'recording')
        .map((item) => `${(item.title || '').trim().toLowerCase()}|${(item.platform || '').trim().toLowerCase()}`)
    )

    const apiOnlyMeetings = apiDerivedMeetings.filter((item) => {
      const key = `${(item.title || '').trim().toLowerCase()}|${(item.platform || '').trim().toLowerCase()}`
      if ((item.status || '').toLowerCase() !== 'recording') return true
      return !existingKeys.has(key)
    })

    return sortMeetings([...meetings, ...apiOnlyMeetings])
  }, [meetings, apiDerivedMeetings])

  const searchedMeetings = useMemo(
    () => allMeetings.filter((meeting) => matchesSmartSearch(meeting, searchIntent)),
    [allMeetings, searchIntent]
  )

  const onlineMeetings = useMemo(
    () => searchedMeetings.filter((meeting) => !OFFLINE_PLATFORMS.has((meeting.platform || '').toLowerCase())),
    [searchedMeetings]
  )

  const offlineMeetings = useMemo(
    () => searchedMeetings.filter((meeting) => OFFLINE_PLATFORMS.has((meeting.platform || '').toLowerCase())),
    [searchedMeetings]
  )

  const notesMeetings = useMemo(() => searchedMeetings.filter((meeting) => meeting.status === 'completed'), [searchedMeetings])

  const dashboardStats = useMemo(
    () => [
      { label: 'Total Meetings', value: allMeetings.length },
      { label: 'Online Meetings', value: onlineMeetings.length },
      { label: 'Offline Meetings', value: offlineMeetings.length },
      { label: 'Active Recordings', value: activeRecordings },
    ],
    [allMeetings.length, onlineMeetings.length, offlineMeetings.length, activeRecordings]
  )

  const hasSmartSearch = smartSearchQuery.trim().length > 0
  const smartSearchSummary = useMemo(() => {
    if (!hasSmartSearch) {
      return 'Try: show meetings where budget was discussed'
    }

    const searchTags = []
    if (searchIntent.scope) searchTags.push(`scope: ${searchIntent.scope}`)
    if (searchIntent.status) searchTags.push(`status: ${searchIntent.status}`)
    if (searchIntent.dateRange) searchTags.push(`date: ${searchIntent.dateRange}`)
    if (searchIntent.tokens.length) searchTags.push(`keywords: ${searchIntent.tokens.join(', ')}`)

    const resultLabel = `${searchedMeetings.length} result${searchedMeetings.length === 1 ? '' : 's'}`
    return `Smart Search found ${resultLabel}${searchTags.length ? ` | ${searchTags.join(' | ')}` : ''}`
  }, [hasSmartSearch, searchIntent, searchedMeetings.length])

  const emptySearchMessage = hasSmartSearch
    ? `No meetings match "${smartSearchQuery.trim()}". Try fewer keywords or a broader phrase.`
    : ''

  const handleCreatedMeeting = async (payload) => {
    setToastMessage(payload?.message || 'Meeting event created.')
    await loadMeetings()
  }

  const handleSignOut = async () => {
    await supabase.auth.signOut()
    setActiveSection('dashboard')
    setActiveDashboardTab('overview')
    setSelectedMeeting(null)
    setShowHero(true)
  }

  const handleEnterFromHero = () => {
    setShowHero(false)
  }

  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-neutral-50 text-neutral-700">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading workspace...
      </div>
    )
  }

  if (showHero) {
    return <HeroPage hasSession={!!session} onEnter={handleEnterFromHero} />
  }

  if (!session) {
    return <AuthScreen />
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_#e2e8f0_0%,_#f8fafc_38%,_#eef2ff_100%)] text-neutral-900">
      <div className="mx-auto flex min-h-screen max-w-[1600px]">
        <aside className="hidden w-[250px] shrink-0 flex-col border-r border-white/80 bg-white/85 px-4 py-5 backdrop-blur md:flex">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-indigo-600">OceanLabs</p>
            <p className="mt-1 text-lg font-semibold">Smart Meetings</p>
          </div>

          <nav className="mt-6 space-y-2">
            <button
              type="button"
              onClick={() => setActiveSection('dashboard')}
              className={`w-full rounded-xl px-3 py-2 text-left text-sm font-semibold transition ${
                activeSection === 'dashboard'
                  ? 'bg-indigo-600 text-white shadow-md shadow-indigo-300/50'
                  : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200'
              }`}
            >
              Dashboard
            </button>
            <button
              type="button"
              onClick={() => setActiveSection('settings')}
              className={`w-full rounded-xl px-3 py-2 text-left text-sm font-semibold transition ${
                activeSection === 'settings'
                  ? 'bg-indigo-600 text-white shadow-md shadow-indigo-300/50'
                  : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200'
              }`}
            >
              Settings
            </button>
          </nav>

          <div className="mt-6 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs text-indigo-700">
            Meeting assistant is active for online capture sessions.
          </div>

          <div className="mt-auto">
            <Button variant="outline" className="w-full border-neutral-300" onClick={handleSignOut}>
              Sign Out
            </Button>
          </div>
        </aside>

        <main className={`flex-1 p-4 md:p-7 ${selectedMeeting ? 'pr-4 md:pr-[430px]' : ''}`}>
          <div className="mb-4 rounded-xl border border-white/80 bg-white/80 p-3 md:hidden">
            <div className="mb-2 flex gap-2">
              <button
                type="button"
                onClick={() => setActiveSection('dashboard')}
                className={`flex-1 rounded-lg px-3 py-2 text-sm font-semibold ${
                  activeSection === 'dashboard' ? 'bg-indigo-600 text-white' : 'bg-neutral-100 text-neutral-600'
                }`}
              >
                Dashboard
              </button>
              <button
                type="button"
                onClick={() => setActiveSection('settings')}
                className={`flex-1 rounded-lg px-3 py-2 text-sm font-semibold ${
                  activeSection === 'settings' ? 'bg-indigo-600 text-white' : 'bg-neutral-100 text-neutral-600'
                }`}
              >
                Settings
              </button>
            </div>
            <Button variant="outline" className="w-full border-neutral-300" onClick={handleSignOut}>
              Sign Out
            </Button>
          </div>

          <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-neutral-500">Welcome</p>
              <h1 className="text-2xl font-semibold text-neutral-900">
                {activeSection === 'dashboard' ? 'Dashboard' : 'Settings'}
              </h1>
              <p className="text-sm text-neutral-600">{session.user.email}</p>
            </div>

            {activeSection === 'dashboard' ? (
              <StartRecordingDialog onCreated={handleCreatedMeeting} triggerLabel="Create Event" />
            ) : null}
          </header>

          {toastMessage ? (
            <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              {toastMessage}
            </div>
          ) : null}

          {activeSection === 'settings' ? (
            <SettingsView
              session={session}
              onUpdatedProfile={() => {
                supabase.auth.getSession().then(({ data }) => setSession(data.session))
              }}
            />
          ) : (
            <section className="space-y-5">
              {meetingsError ? (
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                  <p>{meetingsError}</p>
                  <Button variant="outline" size="sm" className="mt-2 border-amber-300" onClick={loadMeetings}>
                    Retry
                  </Button>
                </div>
              ) : null}

              <div className="rounded-2xl border border-neutral-200 bg-white/85 p-4 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="inline-flex items-center gap-2 text-sm font-semibold text-neutral-800">
                    <Search className="h-4 w-4 text-indigo-500" />
                    Smart Search
                  </p>
                  {hasSmartSearch ? (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 border-neutral-300 text-xs"
                      onClick={() => setSmartSearchQuery('')}
                    >
                      Clear Search
                    </Button>
                  ) : null}
                </div>

                <div className="relative mt-3">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
                  <Input
                    value={smartSearchQuery}
                    onChange={(event) => setSmartSearchQuery(event.target.value)}
                    placeholder="Try: show meetings where budget was discussed"
                    className="h-10 border-neutral-200 bg-neutral-50 pl-9"
                  />
                </div>

                <p className="mt-2 text-xs text-neutral-500">{smartSearchSummary}</p>
              </div>

              <Tabs value={activeDashboardTab} onValueChange={setActiveDashboardTab} className="gap-4">
                <TabsList className="h-10 rounded-xl border border-neutral-200 bg-white/70 p-1">
                  <TabsTrigger value="overview" className="rounded-lg px-3 text-sm">Overview</TabsTrigger>
                  <TabsTrigger value="online" className="rounded-lg px-3 text-sm">Online Meetings</TabsTrigger>
                  <TabsTrigger value="offline" className="rounded-lg px-3 text-sm">Offline Meetings</TabsTrigger>
                  <TabsTrigger value="notes" className="rounded-lg px-3 text-sm">Meeting Notes</TabsTrigger>
                </TabsList>

                <TabsContent value="overview" className="space-y-5">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    {dashboardStats.map((stat) => (
                      <article key={stat.label} className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm">
                        <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">{stat.label}</p>
                        <p className="mt-2 text-2xl font-semibold text-neutral-900">{stat.value}</p>
                      </article>
                    ))}
                  </div>

                  {meetingsLoading ? (
                    <div className="flex items-center justify-center rounded-2xl border border-neutral-200 bg-white px-4 py-14 text-sm text-neutral-600">
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Loading meetings...
                    </div>
                  ) : (
                    <MeetingGrid
                      meetings={hasSmartSearch ? searchedMeetings : searchedMeetings.slice(0, 8)}
                      onOpenMeeting={setSelectedMeeting}
                      emptyMessage={emptySearchMessage || 'No meetings created yet. Use Create Event to start online recording or add offline notes.'}
                    />
                  )}
                </TabsContent>

                <TabsContent value="online">
                  {meetingsLoading ? (
                    <div className="flex items-center justify-center rounded-2xl border border-neutral-200 bg-white px-4 py-14 text-sm text-neutral-600">
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Loading online meetings...
                    </div>
                  ) : (
                    <MeetingGrid
                      meetings={onlineMeetings}
                      onOpenMeeting={setSelectedMeeting}
                      emptyMessage={emptySearchMessage || 'No online meetings found. Create an online event and share meeting link.'}
                    />
                  )}
                </TabsContent>

                <TabsContent value="offline">
                  {meetingsLoading ? (
                    <div className="flex items-center justify-center rounded-2xl border border-neutral-200 bg-white px-4 py-14 text-sm text-neutral-600">
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Loading offline meetings...
                    </div>
                  ) : (
                    <MeetingGrid
                      meetings={offlineMeetings}
                      onOpenMeeting={setSelectedMeeting}
                      emptyMessage={emptySearchMessage || 'No offline meetings found. Create an offline event and add details of who spoke what.'}
                    />
                  )}
                </TabsContent>

                <TabsContent value="notes">
                  {meetingsLoading ? (
                    <div className="flex items-center justify-center rounded-2xl border border-neutral-200 bg-white px-4 py-14 text-sm text-neutral-600">
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Loading meeting notes...
                    </div>
                  ) : (
                    <MeetingGrid
                      meetings={notesMeetings}
                      onOpenMeeting={setSelectedMeeting}
                      emptyMessage={emptySearchMessage || 'No completed notes yet. Notes appear after online recording completes or offline notes are saved.'}
                    />
                  )}
                </TabsContent>
              </Tabs>
            </section>
          )}
        </main>
      </div>

      <MeetingNotesPanel
        meeting={selectedMeeting}
        transcripts={transcripts}
        loading={transcriptsLoading}
        onClose={() => setSelectedMeeting(null)}
      />

      <div className="pointer-events-none fixed bottom-4 left-4 hidden items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 md:flex">
        <Video className="h-3.5 w-3.5" />
        Meeting assistant online capture enabled
      </div>

      {activeRecordings > 0 ? (
        <div className="pointer-events-none fixed bottom-4 right-4 flex items-center gap-2 rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-lg shadow-emerald-300/60">
          <Mic className="h-3.5 w-3.5" />
          {activeRecordings} recording {activeRecordings > 1 ? 'sessions' : 'session'} running
        </div>
      ) : null}
    </div>
  )
}
