import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, useScroll, useTransform, AnimatePresence } from 'framer-motion'
import { Activity, ArrowRight, CheckCircle2, Database, Globe2, Loader2, Mic, Search, Sparkles, X } from 'lucide-react'
import Lenis from '@studio-freight/lenis'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { supabase } from './lib/supabase'
import {
  disconnectIntegration,
  getRecordingDetails,
  getIntegrationsStatus,
  listRecordings,
  runIntegrationsSmokeTest,
  saveIntegrationConfig,
  startRecordingStream,
  startIntegrationOAuth,
} from './lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { StartRecordingDialog } from '@/components/StartRecordingDialog'

const OFFLINE_PLATFORMS = new Set(['offline', 'local'])
const PLATFORM_ALIASES = {
  'google meet': 'meet',
  google_meet: 'meet',
  gmeet: 'meet',
  meet: 'meet',
  'microsoft teams': 'teams',
  microsoft_teams: 'teams',
  'ms teams': 'teams',
  ms_teams: 'teams',
  teams: 'teams',
  zoom: 'zoom',
  'zoom meeting': 'zoom',
  zoom_meeting: 'zoom',
  offline: 'offline',
  local: 'local',
}

const PLATFORM_LABELS = {
  meet: 'Google Meet',
  teams: 'Microsoft Teams',
  zoom: 'Zoom',
  local: 'Offline',
  offline: 'Offline',
}

const SMART_SEARCH_STOP_WORDS = new Set([
  'show', 'me', 'meeting', 'meetings', 'where', 'was', 'were', 'is', 'are', 'the', 'a', 'an',
  'discussed', 'about', 'that', 'with', 'which', 'find', 'all', 'please', 'in', 'to', 'for',
])

const SMART_SEARCH_SUGGESTIONS = [
  { label: 'Today online', query: 'online today' },
  { label: 'Completed this week', query: 'completed this week' },
  { label: 'Offline decisions', query: 'offline decisions' },
  { label: 'Live recordings', query: 'recording live' },
]

function normalizePlatform(value, fallback = 'meet') {
  const normalized = (value || '').toString().trim().toLowerCase()
  if (!normalized) return fallback
  return PLATFORM_ALIASES[normalized] || normalized
}

function formatPlatformLabel(value) {
  const normalized = normalizePlatform(value, 'meet')
  return PLATFORM_LABELS[normalized] || normalized
}

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
    platform: null,
    language: null,
  }

  if (!normalized) return intent

  if (/\bonline\b/.test(normalized)) intent.scope = 'online'
  if (/\boffline\b/.test(normalized)) intent.scope = 'offline'

  if (/\brecording\b|\blive\b|\bin progress\b/.test(normalized)) intent.status = 'recording'
  if (/\bcompleted\b|\bdone\b|\bfinished\b/.test(normalized)) intent.status = 'completed'

  if (/\btoday\b/.test(normalized)) intent.dateRange = 'today'
  if (/\byesterday\b/.test(normalized)) intent.dateRange = 'yesterday'
  if (/\bthis week\b|\bweek\b/.test(normalized)) intent.dateRange = 'week'
  if (/\bthis month\b|\bmonth\b/.test(normalized)) intent.dateRange = 'month'

  if (/\bgoogle meet\b|\bmeet\b/.test(normalized)) intent.platform = 'meet'
  if (/\bmicrosoft teams\b|\bteams\b/.test(normalized)) intent.platform = 'teams'
  if (/\bzoom\b/.test(normalized)) intent.platform = 'zoom'

  if (/\bhindi\b/.test(normalized)) intent.language = 'hi'
  if (/\bgujarati\b/.test(normalized)) intent.language = 'gu'
  if (/\benglish\b/.test(normalized)) intent.language = 'en'

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

  if (dateRange === 'yesterday') {
    const yesterday = new Date(current)
    yesterday.setDate(current.getDate() - 1)
    return createdAt.toDateString() === yesterday.toDateString()
  }

  if (dateRange === 'week') {
    const sevenDaysMs = 7 * 24 * 60 * 60 * 1000
    return current.getTime() - createdAt.getTime() <= sevenDaysMs
  }

  if (dateRange === 'month') {
    return createdAt.getMonth() === current.getMonth() && createdAt.getFullYear() === current.getFullYear()
  }

  return true
}

function evaluateSmartSearch(meeting, intent) {
  if (!intent.raw) {
    return {
      matched: true,
      score: 0,
      matchedTokens: [],
    }
  }

  const platform = (meeting.platform || '').toLowerCase()
  const status = (meeting.status || '').toLowerCase()
  const language = (meeting.language || '').toLowerCase()
  const isOffline = OFFLINE_PLATFORMS.has(platform)

  if (intent.scope === 'online' && isOffline) return { matched: false, score: 0, matchedTokens: [] }
  if (intent.scope === 'offline' && !isOffline) return { matched: false, score: 0, matchedTokens: [] }
  if (intent.status && status !== intent.status) return { matched: false, score: 0, matchedTokens: [] }
  if (intent.platform && platform !== intent.platform) return { matched: false, score: 0, matchedTokens: [] }
  if (intent.language && !language.includes(intent.language)) return { matched: false, score: 0, matchedTokens: [] }
  if (!isWithinDateRange(meeting.createdAt, intent.dateRange)) return { matched: false, score: 0, matchedTokens: [] }

  const titleHaystack = (meeting.title || '').toLowerCase()
  const summaryHaystack = (meeting.summary || '').toLowerCase()
  const metaHaystack = [meeting.language, meeting.platform, meeting.status].join(' ').toLowerCase()

  let score = 0
  const matchedTokens = []

  if (intent.tokens.length) {
    for (const token of intent.tokens) {
      if (titleHaystack.includes(token)) {
        score += 6
        matchedTokens.push(token)
        continue
      }

      if (summaryHaystack.includes(token)) {
        score += 4
        matchedTokens.push(token)
        continue
      }

      if (metaHaystack.includes(token)) {
        score += 2
        matchedTokens.push(token)
      }
    }

    const minimumMatches = Math.max(1, Math.ceil(intent.tokens.length * 0.4))
    if (matchedTokens.length < minimumMatches) {
      return { matched: false, score: 0, matchedTokens: [] }
    }

    if (matchedTokens.length === intent.tokens.length) score += 2
  } else {
    score += 1
  }

  if (intent.scope) score += 1
  if (intent.status) score += 1
  if (intent.platform) score += 1
  if (intent.language) score += 1

  return {
    matched: true,
    score,
    matchedTokens,
  }
}

function inferMeetingPlatform(row) {
  const normalizedPlatform = normalizePlatform(row?.platform, '')
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

function shortenText(text, limit = 240) {
  const normalized = (text || '').replace(/\s+/g, ' ').trim()
  if (!normalized) {
    return 'No summary available yet. Open notes to capture transcript highlights and key decisions.'
  }
  if (normalized.length <= limit) return normalized
  return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}...`
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

function mergeRecordingLivePayload(entry, payload) {
  if (!entry || !payload || typeof payload !== 'object') return entry

  const next = { ...entry }

  const status = (payload.status || '').toString().trim().toLowerCase()
  if (status) next.status = status

  const activeSpeaker = (payload.active_speaker || '').toString().trim()
  if (activeSpeaker) next.active_speaker = activeSpeaker

  if (Array.isArray(payload.participants)) {
    next.participants = payload.participants
      .map((value) => `${value || ''}`.trim())
      .filter(Boolean)
  }

  const elapsedSeconds = Number(payload.elapsed_seconds)
  if (Number.isFinite(elapsedSeconds)) {
    next.elapsed_seconds = Number(elapsedSeconds.toFixed(2))
  }

  const lastAudioRms = Number(payload.last_audio_rms)
  if (Number.isFinite(lastAudioRms)) {
    next.last_audio_rms = Number(lastAudioRms.toFixed(6))
  }

  const latestCaption = (payload.caption_text || '').toString().trim()
  if (latestCaption) {
    next.latest_caption_text = latestCaption
  }

  if (typeof payload.summary === 'string' && payload.summary.trim()) {
    next.summary = payload.summary.trim()
  }

  if (typeof payload.error === 'string' && payload.error.trim()) {
    next.error = payload.error.trim()
  }

  return next
}

function buildLiveCaptionTranscriptLine(payload, fallbackStartSeconds = 0) {
  if (!payload || typeof payload !== 'object') return null

  const spokenText = (payload.caption_text || '').toString().trim()
  if (!spokenText) return null

  const speakerName = (payload.active_speaker || 'Participant').toString().trim() || 'Participant'
  const elapsed = Number(payload.elapsed_seconds)
  const startTimeSeconds = Number.isFinite(elapsed) ? Math.max(0, elapsed) : Math.max(0, fallbackStartSeconds)
  const ts = Number(payload.timestamp)
  const uniqueSuffix = Number.isFinite(ts) ? ts : Date.now()

  return {
    id: `live-line-${uniqueSuffix}`,
    speaker_name: speakerName,
    spoken_text: spokenText,
    start_time_seconds: startTimeSeconds,
  }
}

function isMissingColumnError(error, columnName) {
  const details = `${error?.message || ''} ${error?.details || ''} ${error?.hint || ''}`.toLowerCase()
  if (!details.includes((columnName || '').toLowerCase())) return false
  return (
    details.includes('column') ||
    details.includes('schema cache') ||
    details.includes('does not exist') ||
    details.includes('could not find')
  )
}

function HeroPage({ hasSession, onEnter }) {
  useEffect(() => {
    const lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)), 
      direction: 'vertical', 
      gestureDirection: 'vertical', 
      smooth: true,
      mouseMultiplier: 1,
      smoothTouch: false,
      touchMultiplier: 2,
      infinite: false,
    })

    function raf(time) {
      lenis.raf(time)
      requestAnimationFrame(raf)
    }

    requestAnimationFrame(raf)
    return () => lenis.destroy()
  }, [])

  const { scrollY } = useScroll()
  const opacity = useTransform(scrollY, [0, 400], [1, 0])
  const scale = useTransform(scrollY, [0, 500], [1, 0.85])
  const heroTextY = useTransform(scrollY, [0, 500], [0, 150])

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

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.2
      }
    }
  }

  const itemVariants = {
    hidden: { opacity: 0, y: 40 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 1.2,
        ease: [0.16, 1, 0.3, 1]
      }
    }
  }

  return (
    <div className="relative min-h-screen w-full bg-slate-950 text-white selection:bg-teal-500/30 font-sans">
      {/* Sleek Dark Glows */}
      <div className="pointer-events-none fixed -left-[20%] -top-[20%] h-[60vw] w-[60vw] rounded-full bg-teal-900/20 blur-[160px]" />
      <div className="pointer-events-none fixed -right-[15%] top-[10%] h-[50vw] w-[50vw] rounded-full bg-amber-900/15 blur-[160px]" />

      <motion.div 
        style={{ y: heroTextY, opacity, scale }}
        className="fixed inset-0 top-0 mx-auto flex w-full max-w-[1400px] flex-col items-center justify-center px-6 text-center md:px-10 z-10"
      >
        <motion.div 
          initial="hidden"
          animate="visible"
          variants={containerVariants}
          className="flex flex-col items-center"
        >
          <motion.div variants={itemVariants} className="mb-6 inline-flex items-center gap-2 rounded-full border border-slate-700/70 bg-slate-900/70 py-2 px-5 text-sm font-medium tracking-wide text-slate-300 backdrop-blur-md">
            <Sparkles className="h-4 w-4 text-teal-300" />
            OCEANLABS INTELLIGENCE
          </motion.div>

          <motion.h1 
            variants={itemVariants}
            className="max-w-[14ch] text-6xl font-medium tracking-tighter text-white md:text-8xl lg:text-[7rem] lg:leading-[0.95]"
          >
            MEETINGS THAT MAKE
            <br/> 
            <span className="hero-accent-word text-transparent bg-clip-text italic pr-4">SENSE.</span>
          </motion.h1>

          <motion.p 
            variants={itemVariants}
            className="mt-10 max-w-[45ch] text-lg font-light leading-relaxed text-slate-400 md:text-2xl"
          >
            Capture conversations seamlessly. Distill noise into actionable intelligence. Push decisions straight to your tools.
          </motion.p>

          <motion.div variants={itemVariants} className="mt-14 flex items-center justify-center">
            <Button 
              onClick={onEnter} 
              className="group relative flex h-16 transform items-center justify-center overflow-hidden rounded-full border border-slate-600/80 bg-teal-500 px-10 text-lg font-semibold text-slate-950 transition-all hover:scale-[1.02] hover:bg-teal-400 hover:shadow-[0_0_36px_rgba(20,184,166,0.35)]"
            >
              <span className="relative z-10 flex items-center gap-2">
                {hasSession ? 'Enter Dashboard' : 'Get Started Free'}
                <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
              </span>
            </Button>
          </motion.div>
        </motion.div>
      </motion.div>

      {/* Feature Section inspired by Ribbit.dk scroll reveal */}
      <div className="relative z-20 mt-[88vh] w-full rounded-t-[3rem] bg-slate-950 shadow-[0_-20px_50px_rgba(0,0,0,0.8)] pt-28 pb-24">
        <div className="mx-auto max-w-[1400px] px-6 md:px-10">
          <motion.h2 
            initial={{ opacity: 0, y: 50 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
            className="mb-20 text-center text-4xl font-medium tracking-tight text-white md:text-6xl"
          >
            How it works
          </motion.h2>

          <div className="grid gap-10 md:grid-cols-3">
            {storySteps.map((step, index) => (
              <motion.div 
                key={step.title}
                initial={{ opacity: 0, y: 100 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-50px" }}
                transition={{ duration: 1, delay: index * 0.15, ease: [0.16, 1, 0.3, 1] }}
                className="group relative overflow-hidden rounded-[2rem] border border-slate-700/70 bg-slate-900/70 p-10 transition-all hover:-translate-y-2 hover:border-slate-600/80 hover:bg-slate-800/80 backdrop-blur-sm"
              >
                <div className="mb-8 flex h-14 w-14 items-center justify-center rounded-full bg-slate-800/80 text-2xl font-light text-white transition-colors group-hover:bg-teal-500/20 group-hover:text-teal-300">
                  0{index + 1}
                </div>
                <h3 className="mb-4 text-3xl font-medium tracking-tight text-white">{step.title}</h3>
                <p className="text-lg font-light leading-relaxed text-slate-400">{step.description}</p>
              </motion.div>
            ))}
          </div>
        </div>
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
    <div className="flex min-h-screen items-center justify-center bg-slate-950 text-white px-4 py-10 selection:bg-teal-500/30">
      <div className="pointer-events-none fixed -left-[10%] -top-[10%] h-[40vw] w-[40vw] rounded-full bg-teal-900/10 blur-[110px]" />
      <div className="pointer-events-none fixed -right-[5%] bottom-[10%] h-[30vw] w-[30vw] rounded-full bg-amber-900/10 blur-[110px]" />
      <div className="relative w-full max-w-[440px] rounded-[2rem] border border-slate-700/70 bg-slate-900/70 p-8 shadow-2xl backdrop-blur-xl">
        <div className="mb-8">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-slate-800/80 text-teal-300 mb-4">
            <Sparkles className="h-5 w-5" />
          </div>
          <h1 className="text-3xl font-medium tracking-tight text-white mb-2">OceanLabs</h1>
          <p className="text-base font-light text-slate-400">Sign in to your intelligent workspace.</p>
        </div>

        {error ? <div className="mb-6 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">{error}</div> : null}
        {notice ? <div className="mb-6 rounded-xl border border-teal-400/25 bg-teal-500/10 px-4 py-3 text-sm text-teal-300">{notice}</div> : null}

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'signup' && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium uppercase tracking-wider text-slate-400">Full Name</label>
              <Input required value={fullName} onChange={(e) => setFullName(e.target.value)} className="h-12 border-slate-700/70 bg-slate-900/70 text-white placeholder:text-white/20 focus-visible:ring-teal-500/40" />
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-medium uppercase tracking-wider text-slate-400">Email</label>
            <Input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="h-12 border-slate-700/70 bg-slate-900/70 text-white placeholder:text-white/20 focus-visible:ring-teal-500/40" />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium uppercase tracking-wider text-slate-400">Password</label>
            <Input required type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-12 border-slate-700/70 bg-slate-900/70 text-white placeholder:text-white/20 focus-visible:ring-teal-500/40" />
          </div>

          <Button type="submit" disabled={loading} className="mt-2 h-12 w-full rounded-xl border border-slate-600/80 bg-teal-500 text-slate-950 font-semibold hover:bg-teal-400">
            {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : mode === 'login' ? 'Sign In' : 'Create Account'}
          </Button>

          <p className="mt-6 text-center text-sm font-light text-slate-400">
            {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
            <button type="button" onClick={() => setMode(mode === 'login' ? 'signup' : 'login')} className="font-medium text-teal-300 hover:text-teal-300">
              {mode === 'login' ? 'Sign up' : 'Sign in'}
            </button>
          </p>
        </form>
      </div>
    </div>
  )
}

function MeetingGrid({ meetings, onOpenMeeting, emptyMessage }) {
  if (!meetings.length) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-700/70 bg-slate-900/70 px-6 py-12 text-center text-sm text-slate-400">
        {emptyMessage}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      {meetings.map((meeting) => (
        <article
          key={meeting.id}
          className="group relative overflow-hidden rounded-[2rem] border border-slate-700/70 bg-slate-900/70 p-6 shadow-2xl backdrop-blur-xl transition-all hover:-translate-y-2 hover:border-slate-600/80 hover:bg-slate-800/80"
        >
          <div className="pointer-events-none absolute -inset-px rounded-[2rem] border border-white/5 opacity-0 transition-opacity group-hover:opacity-100" />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-white">{meeting.title}</h3>
            <span className="rounded-full bg-slate-900/70 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              {formatPlatformLabel(meeting.platform)}
            </span>
          </div>

          <p className="mt-1 text-xs text-slate-400">{formatDate(meeting.createdAt)}</p>

          <div className="mt-3 flex flex-wrap gap-2">
            <span className="rounded-md bg-teal-500/10 border border-teal-400/25 px-2 py-1 text-[11px] font-medium tracking-wide text-teal-300">{meeting.language}</span>
            <span className="rounded-md bg-emerald-500/10 border border-emerald-500/20 px-2 py-1 text-[11px] font-medium tracking-wide text-emerald-400">{meeting.status}</span>
          </div>

          <p className="mt-3 line-clamp-2 text-sm text-slate-400">
            {meeting.summary || 'No summary yet. Open notes to see transcript segments and updates.'}
          </p>

          <div className="mt-4 flex justify-end">
            <Button variant="outline" size="sm" onClick={() => onOpenMeeting(meeting)} className="border-slate-700/70">
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
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 10, scale: 0.98 }}
        transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
        className="flex h-[min(88vh,780px)] w-full max-w-4xl flex-col overflow-hidden rounded-3xl border border-slate-700/70 bg-slate-950/95 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-slate-700/70 px-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-white">{meeting.title}</p>
            <p className="text-xs text-slate-400">{formatPlatformLabel(meeting.platform)} - {meeting.language}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-2 text-slate-400 transition hover:bg-slate-800/80 hover:text-white"
            aria-label="Close notes"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {meeting.summary ? (
          <section className="border-b border-slate-700/70 bg-teal-500/10 px-5 py-4">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-teal-300">Summary</p>
            <p className="text-sm leading-relaxed text-white/90">{meeting.summary}</p>
          </section>
        ) : null}

        <section className="flex-1 overflow-y-auto px-4 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-slate-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading transcript...
            </div>
          ) : transcripts.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-700/70 bg-slate-900/70 px-4 py-10 text-center">
              <Activity className="h-6 w-6 text-slate-500" />
              <p className="text-sm font-medium text-slate-400">No transcript lines yet</p>
              <p className="text-xs text-slate-400">
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
                  <article key={line.id || `${line.speaker_name}-${index}`} className="rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2.5">
                    <p className="mb-1 text-[11px] font-semibold text-slate-400">
                      {line.speaker_name || 'Participant'} - {timeLabel}
                    </p>
                    <p className="text-[13px] leading-relaxed text-white/90">{line.spoken_text}</p>
                  </article>
                )
              })}
            </div>
          )}
        </section>
      </motion.div>
    </motion.div>
  )
}

function SettingsView({ session }) {
  const location = useLocation()
  const navigate = useNavigate()
  const sessionUserId = (session?.user?.id || '').trim()

  const [integrationState, setIntegrationState] = useState(null)
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [testingIntegrations, setTestingIntegrations] = useState(false)
  const [oauthBusyProvider, setOauthBusyProvider] = useState('')
  const [savingProvider, setSavingProvider] = useState('')
  const [integrationsError, setIntegrationsError] = useState('')
  const [oauthNotice, setOauthNotice] = useState('')
  const [lastTestResult, setLastTestResult] = useState(null)
  const [configForm, setConfigForm] = useState({
    slack: { channel_id: '' },
    jira: { project_key: '', issue_type: 'Task' },
    notion: { database_id: '', parent_page_id: '', title_property: 'Name' },
  })

  const refreshIntegrations = useCallback(async () => {
    if (!sessionUserId) {
      setIntegrationState(null)
      setLoadingStatus(false)
      return
    }

    setLoadingStatus(true)
    setIntegrationsError('')
    try {
      const status = await getIntegrationsStatus()
      setIntegrationState(status)
    } catch (error) {
      setIntegrationsError(error?.message || 'Unable to load integration status from backend.')
    } finally {
      setLoadingStatus(false)
    }
  }, [sessionUserId])

  useEffect(() => {
    refreshIntegrations()
  }, [refreshIntegrations])

  useEffect(() => {
    const services = integrationState?.services || {}
    setConfigForm((prev) => ({
      slack: {
        channel_id: services?.slack?.config?.channel_id || prev.slack.channel_id || '',
      },
      jira: {
        project_key: services?.jira?.config?.project_key || prev.jira.project_key || '',
        issue_type: services?.jira?.config?.issue_type || prev.jira.issue_type || 'Task',
      },
      notion: {
        database_id: services?.notion?.config?.database_id || prev.notion.database_id || '',
        parent_page_id: services?.notion?.config?.parent_page_id || prev.notion.parent_page_id || '',
        title_property: services?.notion?.config?.title_property || prev.notion.title_property || 'Name',
      },
    }))
  }, [integrationState])

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const oauthStatus = params.get('oauth')
    if (!oauthStatus) return

    const provider = params.get('provider') || 'integration'
    const message = params.get('message') || 'OAuth flow completed.'

    if (oauthStatus === 'success') {
      setOauthNotice(`${provider.toUpperCase()} connected: ${message}`)
      setIntegrationsError('')
    } else {
      setIntegrationsError(`${provider.toUpperCase()} OAuth failed: ${message}`)
      setOauthNotice('')
    }

    navigate('/settings', { replace: true })
    refreshIntegrations()
  }, [location.search, navigate, refreshIntegrations])

  const updateProviderConfig = (provider, key, value) => {
    setConfigForm((prev) => ({
      ...prev,
      [provider]: {
        ...(prev[provider] || {}),
        [key]: value,
      },
    }))
  }

  const handleConnectOAuth = async (provider) => {
    if (!sessionUserId) {
      setIntegrationsError('Please sign in before connecting integrations.')
      return
    }

    setOauthBusyProvider(provider)
    setIntegrationsError('')
    try {
      const nextUrl = `${window.location.origin}/settings`
      const data = await startIntegrationOAuth(provider, nextUrl)
      const authUrl = data?.authorization_url
      if (!authUrl) throw new Error('OAuth URL was not returned by backend.')
      window.location.assign(authUrl)
    } catch (error) {
      setIntegrationsError(error?.message || `Could not start ${provider} OAuth flow.`)
      setOauthBusyProvider('')
    }
  }

  const handleDisconnect = async (provider) => {
    if (!sessionUserId) return

    setOauthBusyProvider(provider)
    setIntegrationsError('')
    setOauthNotice('')
    try {
      await disconnectIntegration({ provider })
      await refreshIntegrations()
      setOauthNotice(`${provider.toUpperCase()} disconnected.`)
    } catch (error) {
      setIntegrationsError(error?.message || `Could not disconnect ${provider}.`)
    } finally {
      setOauthBusyProvider('')
    }
  }

  const handleSaveConfig = async (provider) => {
    if (!sessionUserId) {
      setIntegrationsError('Please sign in before saving integration configuration.')
      return
    }

    const providerConfig = configForm?.[provider] || {}
    setSavingProvider(provider)
    setIntegrationsError('')
    setOauthNotice('')
    try {
      await saveIntegrationConfig({
        provider,
        config: providerConfig,
      })
      await refreshIntegrations()
      setOauthNotice(`${provider.toUpperCase()} configuration saved.`)
    } catch (error) {
      setIntegrationsError(error?.message || `Could not save ${provider} configuration.`)
    } finally {
      setSavingProvider('')
    }
  }

  const handleRunIntegrationsSmoke = async () => {
    if (!sessionUserId) {
      setIntegrationsError('Please sign in before running integration smoke tests.')
      return
    }

    setTestingIntegrations(true)
    setIntegrationsError('')
    try {
      const data = await runIntegrationsSmokeTest({
        title: 'Website Integrations Smoke',
        platform: 'local',
        language: 'en',
        user_id: sessionUserId,
      })
      setLastTestResult(data?.result || null)
      await refreshIntegrations()
    } catch (error) {
      setIntegrationsError(error?.message || 'Smoke test failed to run.')
    } finally {
      setTestingIntegrations(false)
    }
  }

  const services = integrationState?.services || {}
  const oauthAvailable = integrationState?.oauth_available !== false
  const integrations = [
    {
      key: 'slack',
      label: 'Slack',
      detail: 'Publishes meeting digest into the configured channel.',
    },
    {
      key: 'jira',
      label: 'Jira',
      detail: 'Creates issue cards from meeting outcomes.',
    },
    {
      key: 'notion',
      label: 'Notion',
      detail: 'Writes meeting summaries into your workspace database/page.',
    },
  ]

  const readyCount = integrationState?.ready_count || 0
  const totalCount = integrationState?.total_count || integrations.length

  return (
    <div className="max-w-5xl animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="space-y-8">
        <section className="rounded-3xl border border-slate-700/70 bg-slate-900/70 p-8 backdrop-blur-xl shadow-2xl">
          <h2 className="text-2xl font-medium tracking-tight text-white mb-2">Profile Settings</h2>
          <p className="text-sm font-light text-slate-400 mb-6">Manage your account details and configuration.</p>
          <div className="space-y-4">
             <div className="rounded-2xl border border-slate-700/70 bg-black/20 p-5">
                <label className="text-xs font-bold uppercase tracking-widest text-slate-400">Account Email</label>
                <p className="mt-2 text-lg font-light text-white">{session?.user?.email || 'N/A'}</p>
             </div>
          </div>
        </section>

        <section className="rounded-3xl border border-slate-700/70 bg-slate-900/70 p-8 backdrop-blur-xl shadow-2xl">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-2xl font-medium tracking-tight text-white">Integrations Control Center</h2>
              <p className="mt-1 text-sm font-light text-slate-400">
                Outlook has been removed. Manage Slack, Jira, and Notion directly from the website.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                className="border-slate-600/80 bg-slate-900/70"
                onClick={refreshIntegrations}
                disabled={loadingStatus || testingIntegrations}
              >
                {loadingStatus ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Refresh Status'}
              </Button>

              <Button
                type="button"
                className="border border-slate-600/80 bg-teal-500 text-slate-950 hover:bg-teal-400"
                onClick={handleRunIntegrationsSmoke}
                disabled={loadingStatus || testingIntegrations}
              >
                {testingIntegrations ? (
                  <span className="inline-flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Running Test
                  </span>
                ) : (
                  'Run Smoke Test'
                )}
              </Button>
            </div>
          </div>

          <div className="mt-5 rounded-2xl border border-teal-500/20 bg-teal-500/10 px-4 py-3 text-sm text-teal-200">
            {readyCount} of {totalCount} integrations are configured and ready.
          </div>

          {!oauthAvailable ? (
            <div className="mt-4 rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              OAuth endpoints are unavailable on backend. {integrationState?.oauth_error || 'Check backend environment variables for OAuth client setup.'}
            </div>
          ) : null}

          {oauthNotice ? (
            <div className="mt-4 rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
              {oauthNotice}
            </div>
          ) : null}

          {integrationsError ? (
            <div className="mt-4 rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              {integrationsError}
            </div>
          ) : null}

          <div className="mt-5 grid gap-4 md:grid-cols-3">
            {integrations.map((item) => {
              const state = services[item.key] || {
                configured: false,
                mode: 'unknown',
                message: 'Status not available.',
                oauth_connected: false,
                config: {},
              }
              const providerConfig = configForm[item.key] || {}
              const isBusy = oauthBusyProvider === item.key
              const isSaving = savingProvider === item.key

              return (
                <article
                  key={item.key}
                  className="rounded-2xl border border-slate-700/70 bg-black/20 p-4"
                >
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-base font-semibold text-white">{item.label}</h3>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${state.configured ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-300'}`}>
                      {state.configured ? 'ready' : 'setup needed'}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-slate-400">{item.detail}</p>
                  <p className="mt-3 text-xs text-slate-300">{state.message}</p>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      className="border border-slate-600/80 bg-teal-500 text-slate-950 hover:bg-teal-400"
                      disabled={!oauthAvailable || loadingStatus || isBusy || testingIntegrations}
                      onClick={() => handleConnectOAuth(item.key)}
                    >
                      {isBusy ? (
                        <span className="inline-flex items-center gap-2">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Connecting
                        </span>
                      ) : state.oauth_connected ? (
                        'Reconnect OAuth'
                      ) : (
                        'Connect OAuth'
                      )}
                    </Button>

                    {state.oauth_connected ? (
                      <Button
                        type="button"
                        variant="outline"
                        className="border-slate-600/80 bg-slate-900/70"
                        disabled={loadingStatus || isBusy || testingIntegrations}
                        onClick={() => handleDisconnect(item.key)}
                      >
                        Disconnect
                      </Button>
                    ) : null}
                  </div>

                  <div className="mt-4 space-y-2">
                    {item.key === 'slack' ? (
                      <>
                        <Input
                          value={providerConfig.channel_id || ''}
                          onChange={(event) => updateProviderConfig('slack', 'channel_id', event.target.value)}
                          className="border-slate-700/70 bg-slate-900/70 text-white"
                          placeholder="Slack channel ID (example: C12345678)"
                        />
                        <p className="text-[11px] text-slate-400">Required for posting with OAuth token mode.</p>
                      </>
                    ) : null}

                    {item.key === 'jira' ? (
                      <>
                        <Input
                          value={providerConfig.project_key || ''}
                          onChange={(event) => updateProviderConfig('jira', 'project_key', event.target.value)}
                          className="border-slate-700/70 bg-slate-900/70 text-white"
                          placeholder="Jira project key (example: PROD)"
                        />
                        <Input
                          value={providerConfig.issue_type || 'Task'}
                          onChange={(event) => updateProviderConfig('jira', 'issue_type', event.target.value)}
                          className="border-slate-700/70 bg-slate-900/70 text-white"
                          placeholder="Issue type (default: Task)"
                        />
                      </>
                    ) : null}

                    {item.key === 'notion' ? (
                      <>
                        <Input
                          value={providerConfig.database_id || ''}
                          onChange={(event) => updateProviderConfig('notion', 'database_id', event.target.value)}
                          className="border-slate-700/70 bg-slate-900/70 text-white"
                          placeholder="Notion database ID"
                        />
                        <Input
                          value={providerConfig.parent_page_id || ''}
                          onChange={(event) => updateProviderConfig('notion', 'parent_page_id', event.target.value)}
                          className="border-slate-700/70 bg-slate-900/70 text-white"
                          placeholder="Notion parent page ID (optional if database ID set)"
                        />
                        <Input
                          value={providerConfig.title_property || 'Name'}
                          onChange={(event) => updateProviderConfig('notion', 'title_property', event.target.value)}
                          className="border-slate-700/70 bg-slate-900/70 text-white"
                          placeholder="Title property name (default: Name)"
                        />
                      </>
                    ) : null}

                    <Button
                      type="button"
                      variant="outline"
                      className="w-full border-slate-600/80 bg-slate-900/70"
                      disabled={loadingStatus || isSaving}
                      onClick={() => handleSaveConfig(item.key)}
                    >
                      {isSaving ? (
                        <span className="inline-flex items-center gap-2">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Saving
                        </span>
                      ) : (
                        'Save Config'
                      )}
                    </Button>
                  </div>
                </article>
              )
            })}
          </div>

          {lastTestResult ? (
            <div className="mt-6 rounded-2xl border border-slate-700/70 bg-black/20 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-white">
                <Sparkles className="h-4 w-4 text-teal-300" />
                Last Smoke Test Result
              </div>

              <div className="mt-3 grid gap-2 md:grid-cols-3">
                {['slack', 'jira', 'notion'].map((serviceKey) => (
                  <div key={`result-${serviceKey}`} className="rounded-lg border border-slate-700/70 bg-slate-900/70 px-3 py-2">
                    <p className="text-[11px] uppercase tracking-wide text-slate-400">{serviceKey}</p>
                    <p className="mt-1 text-sm text-white">{lastTestResult?.[serviceKey] || 'skipped'}</p>
                  </div>
                ))}
              </div>

              {Array.isArray(lastTestResult?.warnings) && lastTestResult.warnings.length ? (
                <div className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                  {lastTestResult.warnings.join(' | ')}
                </div>
              ) : (
                <p className="mt-3 text-xs text-emerald-300">No warnings returned from the latest test run.</p>
              )}
            </div>
          ) : null}
        </section>
      </div>
    </div>
  )
}

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [session, setSession] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)
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
  const [meetingsOwnerColumn, setMeetingsOwnerColumn] = useState('user_id')
  const recordingStreamDisposersRef = useRef(new Map())
  const activeSection = location.pathname === '/settings' ? 'settings' : 'dashboard'

  const loadMeetings = useCallback(async () => {
    setMeetingsLoading(true)
    setMeetingsError('')

    const sessionUserId = session?.user?.id
    if (!sessionUserId) {
      setMeetings([])
      setMeetingsLoading(false)
      return
    }

    const ownerColumns = ['user_id', 'created_by', 'owner_id']
    let loadedRows = null
    let resolvedOwnerColumn = null
    let terminalError = null

    for (const ownerColumn of ownerColumns) {
      const { data, error } = await supabase
        .from('meetings')
        .select('*')
        .eq(ownerColumn, sessionUserId)
        .order('created_at', { ascending: false })

      if (!error) {
        loadedRows = data || []
        resolvedOwnerColumn = ownerColumn
        break
      }

      if (isMissingColumnError(error, ownerColumn)) {
        continue
      }

      terminalError = error
      break
    }

    if (!resolvedOwnerColumn) {
      setMeetingsError(
        terminalError?.message ||
          'Database is not ready for per-user meeting isolation. Run backend/supabase_user_scope_setup.sql in Supabase SQL Editor, then refresh this page.'
      )
      setMeetings([])
      setMeetingsLoading(false)
      return
    }

    if (resolvedOwnerColumn !== meetingsOwnerColumn) {
      setMeetingsOwnerColumn(resolvedOwnerColumn)
    }

    setMeetings(sortMeetings((loadedRows || []).map(normalizeMeeting)))
    setMeetingsLoading(false)
  }, [session?.user?.id, meetingsOwnerColumn])

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
      setMeetingsOwnerColumn('user_id')
      return
    }

    loadMeetings()

    const ownerFilterColumn = meetingsOwnerColumn || 'user_id'

    const channel = supabase
      .channel(`meetings-feed-${session.user.id}`)
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'meetings',
          filter: `${ownerFilterColumn}=eq.${session.user.id}`,
        },
        (payload) => {
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
        }
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [session, loadMeetings, meetingsOwnerColumn])

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
        const running = sessions.filter((entry) => {
          const status = (entry?.status || '').toLowerCase()
          return status === 'recording' || status === 'stopping' || status === 'transcribing'
        }).length
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
    const disposers = recordingStreamDisposersRef.current

    return () => {
      disposers.forEach((dispose) => {
        try {
          dispose?.()
        } catch {
          // No-op cleanup for already-closed stream handlers.
        }
      })
      disposers.clear()
    }
  }, [])

  useEffect(() => {
    const activeUserId = (session?.user?.id || '').trim()
    if (!activeUserId) {
      recordingStreamDisposersRef.current.forEach((dispose) => {
        try {
          dispose?.()
        } catch {
          // Ignore cleanup failures while signing out or switching users.
        }
      })
      recordingStreamDisposersRef.current.clear()
      return
    }

    const shouldStreamStatuses = new Set(['recording', 'stopping', 'transcribing'])
    const desiredRecordingIds = new Set(
      (recordingSessions || [])
        .filter((entry) => shouldStreamStatuses.has((entry?.status || '').toLowerCase()))
        .map((entry) => entry.id)
        .filter(Boolean)
    )

    for (const [recordingId, dispose] of recordingStreamDisposersRef.current.entries()) {
      if (!desiredRecordingIds.has(recordingId)) {
        try {
          dispose?.()
        } catch {
          // Ignore stream teardown issues.
        }
        recordingStreamDisposersRef.current.delete(recordingId)
      }
    }

    desiredRecordingIds.forEach((recordingId) => {
      if (recordingStreamDisposersRef.current.has(recordingId)) return

      const dispose = startRecordingStream(recordingId, {
        onEvent: (payload) => {
          if (!payload || typeof payload !== 'object') return
          setRecordingSessions((prev) =>
            (prev || []).map((entry) => (entry.id === recordingId ? mergeRecordingLivePayload(entry, payload) : entry))
          )
        },
      })

      recordingStreamDisposersRef.current.set(recordingId, dispose)
    })
  }, [recordingSessions, session?.user?.id])

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
  }, [selectedMeeting, session?.user?.id])

  useEffect(() => {
    if (!selectedMeeting?.id?.startsWith('api-')) return undefined

    const recordingId = selectedMeeting.recordingId || selectedMeeting.id.slice(4)
    const activeUserId = (session?.user?.id || '').trim()
    if (!recordingId || !activeUserId) return undefined

    let active = true
    let finalTranscriptFetched = false
    const seenCaptionKeys = new Set()

    const dispose = startRecordingStream(recordingId, {
      onEvent: (payload) => {
        if (!active || !payload || typeof payload !== 'object') return

        setSelectedMeeting((prev) => {
          if (!prev?.id?.startsWith('api-')) return prev
          const prevRecordingId = prev.recordingId || prev.id.slice(4)
          if (prevRecordingId !== recordingId) return prev

          const next = { ...prev }
          const incomingStatus = (payload.status || '').toString().toLowerCase().trim()
          if (incomingStatus) next.status = incomingStatus

          const incomingSpeaker = (payload.active_speaker || '').toString().trim()
          if (incomingSpeaker) next.activeSpeaker = incomingSpeaker

          if (Array.isArray(payload.participants)) {
            next.participants = payload.participants
              .map((item) => `${item || ''}`.trim())
              .filter(Boolean)
          }

          const incomingCaption = (payload.caption_text || '').toString().trim()
          if (incomingCaption) {
            next.latestCaptionText = incomingCaption
            if (!next.summary || next.status === 'recording') {
              next.summary = `Recording is in progress from backend session. Live caption: ${incomingCaption}`
            }
          }

          if (typeof payload.summary === 'string' && payload.summary.trim()) {
            next.summary = payload.summary.trim()
          }

          if (typeof payload.error === 'string' && payload.error.trim()) {
            next.summary = `Recording session failed: ${payload.error.trim()}`
          }

          return next
        })

        if ((payload.type || '').toLowerCase() === 'caption') {
          setTranscripts((prev) => {
            const fallbackStart = Number(prev?.[prev.length - 1]?.start_time_seconds)
            const nextLine = buildLiveCaptionTranscriptLine(payload, Number.isFinite(fallbackStart) ? fallbackStart + 1 : 0)
            if (!nextLine) return prev

            const dedupeKey = `${nextLine.speaker_name.toLowerCase()}|${nextLine.spoken_text.toLowerCase()}|${Math.floor(nextLine.start_time_seconds)}`
            if (seenCaptionKeys.has(dedupeKey)) return prev

            const exists = (prev || []).some((item) => {
              const speaker = (item?.speaker_name || '').toString().toLowerCase()
              const text = (item?.spoken_text || '').toString().toLowerCase()
              const start = Math.floor(Number(item?.start_time_seconds) || 0)
              return `${speaker}|${text}|${start}` === dedupeKey
            })
            if (exists) return prev

            seenCaptionKeys.add(dedupeKey)
            return [...prev, nextLine]
          })
        }

        const status = (payload.status || '').toString().toLowerCase()
        if ((status === 'completed' || status === 'error') && !finalTranscriptFetched) {
          finalTranscriptFetched = true
          getRecordingDetails(recordingId)
            .then((detail) => {
              if (!active) return
              const parsed = parseBackendTranscript(detail?.transcript || '')
              if (parsed.length) setTranscripts(parsed)
            })
            .catch(() => {
              // Keep already streamed lines when final fetch fails.
            })
        }
      },
    })

    return () => {
      active = false
      dispose?.()
    }
  }, [selectedMeeting?.id, selectedMeeting?.recordingId, session?.user?.id])

  useEffect(() => {
    if (!toastMessage) return undefined
    const timer = setTimeout(() => setToastMessage(''), 4200)
    return () => clearTimeout(timer)
  }, [toastMessage])

  const searchIntent = useMemo(() => getSearchIntent(smartSearchQuery), [smartSearchQuery])

  const apiDerivedMeetings = useMemo(() => {
    return recordingSessions.map((entry) => {
      const status = (entry?.status || 'recording').toLowerCase()
      const createdAt = entry?.created_at
        ? new Date(entry.created_at * 1000).toISOString()
        : new Date().toISOString()
      const activeSpeaker = (entry?.active_speaker || '').toString().trim()
      const participants = Array.isArray(entry?.participants)
        ? entry.participants.map((item) => `${item || ''}`.trim()).filter(Boolean)
        : []
      const latestCaptionText = (entry?.latest_caption_text || '').toString().trim()

      const baseSummary =
        status === 'recording'
          ? 'Recording is in progress from backend session.'
          : status === 'stopping' || status === 'transcribing'
            ? 'Recording stopped. Transcription is in progress.'
            : status === 'error'
            ? `Recording session failed: ${entry?.error || 'Unknown error'}`
            : 'Recording session completed in backend runtime.'

      const liveContextBits = []
      if (activeSpeaker) {
        liveContextBits.push(`Active speaker: ${activeSpeaker}.`)
      }
      if (participants.length) {
        liveContextBits.push(`Participants: ${participants.slice(0, 4).join(', ')}.`)
      }
      if (latestCaptionText) {
        liveContextBits.push(`Live caption: ${latestCaptionText}`)
      }
      const liveContext = liveContextBits.length ? ` ${liveContextBits.join(' ')}` : ''

      return {
        id: `api-${entry.id}`,
        recordingId: entry.id,
        title: entry?.title || 'Untitled Meeting',
        platform: normalizePlatform(entry?.platform, 'meet'),
        status,
        language: entry?.language || 'Auto',
        summary: entry?.summary || `${baseSummary}${liveContext}`.trim(),
        createdAt,
        activeSpeaker,
        participants,
        latestCaptionText,
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

  const searchResults = useMemo(() => {
    return allMeetings
      .map((meeting) => ({
        meeting,
        evaluation: evaluateSmartSearch(meeting, searchIntent),
      }))
      .filter((entry) => entry.evaluation.matched)
      .sort((left, right) => {
        const scoreDelta = right.evaluation.score - left.evaluation.score
        if (scoreDelta !== 0) return scoreDelta
        return new Date(right.meeting.createdAt) - new Date(left.meeting.createdAt)
      })
  }, [allMeetings, searchIntent])

  const searchedMeetings = useMemo(
    () => searchResults.map((entry) => entry.meeting),
    [searchResults]
  )

  const topSearchMatches = useMemo(
    () => searchResults.slice(0, 3),
    [searchResults]
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
      { label: 'Total Meetings', value: allMeetings.length, icon: Database, accent: 'bg-teal-400' },
      { label: 'Online Meetings', value: onlineMeetings.length, icon: Globe2, accent: 'bg-amber-400' },
      { label: 'Offline Meetings', value: offlineMeetings.length, icon: CheckCircle2, accent: 'bg-violet-400' },
      { label: 'Active Recordings', value: activeRecordings, icon: Activity, accent: 'bg-emerald-400' },
    ],
    [allMeetings.length, onlineMeetings.length, offlineMeetings.length, activeRecordings]
  )

  const maxDashboardStat = useMemo(
    () => Math.max(1, ...dashboardStats.map((stat) => Number(stat.value) || 0)),
    [dashboardStats]
  )

  const hasSmartSearch = smartSearchQuery.trim().length > 0

  const activeSearchFacets = useMemo(() => {
    const facets = []
    if (searchIntent.scope) facets.push(`scope: ${searchIntent.scope}`)
    if (searchIntent.status) facets.push(`status: ${searchIntent.status}`)
    if (searchIntent.dateRange) facets.push(`date: ${searchIntent.dateRange}`)
    if (searchIntent.platform) facets.push(`platform: ${searchIntent.platform}`)
    if (searchIntent.language) facets.push(`language: ${searchIntent.language.toUpperCase()}`)
    return facets
  }, [searchIntent])

  const latestMeeting = useMemo(() => allMeetings[0] || null, [allMeetings])

  const recentMeetings = useMemo(
    () => searchedMeetings.slice(0, 6),
    [searchedMeetings]
  )

  const completionRate = useMemo(() => {
    if (!allMeetings.length) return 0
    return Math.round((notesMeetings.length / allMeetings.length) * 100)
  }, [allMeetings.length, notesMeetings.length])

  const onlineMix = useMemo(() => {
    if (!allMeetings.length) return 0
    return Math.round((onlineMeetings.length / allMeetings.length) * 100)
  }, [allMeetings.length, onlineMeetings.length])

  const smartSearchSummary = useMemo(() => {
    if (!hasSmartSearch) {
      return 'Try natural language: online meetings this week where budget was discussed'
    }

    const searchTags = []
    if (searchIntent.scope) searchTags.push(`scope: ${searchIntent.scope}`)
    if (searchIntent.status) searchTags.push(`status: ${searchIntent.status}`)
    if (searchIntent.dateRange) searchTags.push(`date: ${searchIntent.dateRange}`)
    if (searchIntent.platform) searchTags.push(`platform: ${searchIntent.platform}`)
    if (searchIntent.language) searchTags.push(`language: ${searchIntent.language.toUpperCase()}`)
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
    setActiveDashboardTab('overview')
    setSelectedMeeting(null)
    navigate('/auth')
  }

  const navigateSection = (section) => {
    navigate(section === 'settings' ? '/settings' : '/dashboard')
  }

  const handleEnterFromHero = () => {
    if (session) {
      navigate('/dashboard')
      return
    }
    navigate('/auth')
  }

  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-300">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading workspace...
      </div>
    )
  }

  if (location.pathname === '/') {
    return <HeroPage hasSession={!!session} onEnter={handleEnterFromHero} />
  }

  if (location.pathname === '/auth') {
    if (session) {
      return <Navigate to="/dashboard" replace />
    }
    return <AuthScreen />
  }

  if (location.pathname !== '/dashboard' && location.pathname !== '/settings') {
    return <Navigate to={session ? '/dashboard' : '/auth'} replace />
  }

  if (!session) {
    return <Navigate to="/auth" replace />
  }

  return (
    <div className="app-shell relative min-h-screen text-white">
      <div className="app-atmosphere" />
      <div className="app-orb app-orb--one" />
      <div className="app-orb app-orb--two" />

      <div className="relative mx-auto flex min-h-screen w-full max-w-[1600px]">
        <aside className="hidden w-[300px] shrink-0 flex-col border-r border-slate-700/70 bg-slate-950/30 px-6 py-8 backdrop-blur-2xl md:flex">
          <div className="rounded-3xl border border-slate-700/70 bg-slate-900/70 p-5 shadow-2xl backdrop-blur-xl">
            <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-teal-300">OceanLabs</p>
            <p className="mt-3 font-display text-2xl font-semibold tracking-tight text-white">Command Center</p>
            <p className="mt-2 text-xs leading-relaxed text-slate-300/80">
              Unified workspace for online and offline meeting intelligence.
            </p>
          </div>

          <nav className="mt-8 space-y-2">
            <button
              type="button"
              onClick={() => navigateSection('dashboard')}
              className={`w-full rounded-2xl px-4 py-3 text-left text-sm font-medium tracking-wide transition-all ${activeSection === 'dashboard' ? 'bg-teal-500 text-white shadow-lg shadow-teal-500/25' : 'bg-slate-900/70 text-slate-300/80 hover:bg-slate-800/80 hover:text-white'}`}
            >
              Dashboard
            </button>
            <button
              type="button"
              onClick={() => navigateSection('settings')}
              className={`w-full rounded-2xl px-4 py-3 text-left text-sm font-medium tracking-wide transition-all ${activeSection === 'settings' ? 'bg-teal-500 text-white shadow-lg shadow-teal-500/25' : 'bg-slate-900/70 text-slate-300/80 hover:bg-slate-800/80 hover:text-white'}`}
            >
              Settings
            </button>
          </nav>

          <div className="mt-8 rounded-2xl border border-teal-400/25 bg-teal-500/10 px-4 py-4 text-xs leading-relaxed text-teal-300">
            <Sparkles className="mb-2 h-4 w-4 inline" />
            Meeting assistant is active and waiting for online capture sessions.
          </div>

          <div className="mt-auto">
            <Button variant="outline" className="w-full border-slate-700/70" onClick={handleSignOut}>
              Sign Out
            </Button>
          </div>
        </aside>

        <main className="flex-1 p-4 md:p-7">
          <div className="mb-6 rounded-2xl border border-slate-700/70 bg-slate-900/70 p-3 shadow-2xl backdrop-blur-xl md:hidden">
            <div className="mb-2 flex gap-2">
              <button
                type="button"
                onClick={() => navigateSection('dashboard')}
                className={`flex-1 rounded-xl px-3 py-2.5 text-sm font-medium transition-all ${ activeSection === "dashboard" ? "bg-teal-500 text-white shadow-lg shadow-teal-500/20" : "bg-transparent text-slate-400 hover:bg-slate-800/80 hover:text-white" }`}
              >
                Dashboard
              </button>
              <button
                type="button"
                onClick={() => navigateSection('settings')}
                className={`flex-1 rounded-xl px-3 py-2.5 text-sm font-medium transition-all ${ activeSection === "settings" ? "bg-teal-500 text-white shadow-lg shadow-teal-500/20" : "bg-transparent text-slate-400 hover:bg-slate-800/80 hover:text-white" }`}
              >
                Settings
              </button>
            </div>
            <Button variant="outline" className="w-full border-slate-700/70" onClick={handleSignOut}>
              Sign Out
            </Button>
          </div>

          <header className="mb-10 flex flex-wrap items-end justify-between gap-5 border-b border-slate-700/70 pb-8">
            <div>
              <p className="mb-3 text-[10px] font-bold uppercase tracking-[0.3em] text-teal-300">Workspace</p>
              <h1 className="font-display text-5xl font-semibold tracking-tight text-white mb-2 md:text-6xl">
                {activeSection === 'dashboard' ? 'Dashboard' : 'Settings'}
              </h1>
              <p className="text-sm font-light text-slate-500">{session.user.email}</p>
            </div>

            {activeSection === 'dashboard' ? (
              <StartRecordingDialog onCreated={handleCreatedMeeting} triggerLabel="Create Event" userId={session?.user?.id} />
            ) : null}
          </header>

          {toastMessage ? (
            <div className="mb-4 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
              {toastMessage}
            </div>
          ) : null}

          {activeSection === 'settings' ? (
            <SettingsView session={session} />
          ) : (
            <section className="space-y-5">
              <div className="grid gap-3 lg:grid-cols-3">
                <button
                  type="button"
                  onClick={() => setActiveDashboardTab('online')}
                  className="group rounded-2xl border border-slate-700/70 bg-slate-900/70 p-4 text-left shadow-xl backdrop-blur-xl transition-all hover:-translate-y-1 hover:bg-slate-800/80"
                >
                  <p className="inline-flex items-center gap-2 text-sm font-semibold text-white">
                    <Globe2 className="h-4 w-4 text-teal-300" />
                    Track Live Rooms
                  </p>
                  <p className="mt-2 text-xs text-slate-300/80">Jump to online meetings and monitor active sessions instantly.</p>
                </button>

                <button
                  type="button"
                  onClick={() => setActiveDashboardTab('offline')}
                  className="group rounded-2xl border border-slate-700/70 bg-slate-900/70 p-4 text-left shadow-xl backdrop-blur-xl transition-all hover:-translate-y-1 hover:bg-slate-800/80"
                >
                  <p className="inline-flex items-center gap-2 text-sm font-semibold text-white">
                    <CheckCircle2 className="h-4 w-4 text-violet-300" />
                    Offline Intelligence
                  </p>
                  <p className="mt-2 text-xs text-slate-300/80">Review manually captured decisions and discussion context.</p>
                </button>

                <button
                  type="button"
                  onClick={() => setActiveDashboardTab('notes')}
                  className="group rounded-2xl border border-slate-700/70 bg-slate-900/70 p-4 text-left shadow-xl backdrop-blur-xl transition-all hover:-translate-y-1 hover:bg-slate-800/80"
                >
                  <p className="inline-flex items-center gap-2 text-sm font-semibold text-white">
                    <Search className="h-4 w-4 text-emerald-300" />
                    Read Final Notes
                  </p>
                  <p className="mt-2 text-xs text-slate-300/80">Open completed summaries and transcript snippets in one click.</p>
                </button>
              </div>

              {meetingsError ? (
                <div className="rounded-xl border border-yellow-500/20 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-500">
                  <p>{meetingsError}</p>
                  <Button variant="outline" size="sm" className="mt-2 border-amber-500/40 text-amber-300 hover:bg-amber-500/10" onClick={loadMeetings}>
                    Retry
                  </Button>
                </div>
              ) : null}

              <div className="grid gap-4 xl:grid-cols-[1.7fr_1fr]">
                <div className="rounded-[2rem] border border-slate-700/70 bg-slate-900/70 p-6 shadow-2xl backdrop-blur-xl">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="inline-flex items-center gap-2 text-sm font-semibold text-white">
                      <Search className="h-4 w-4 text-teal-300" />
                      Smart Search
                    </p>
                    {hasSmartSearch ? (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 border-slate-700/70 text-xs"
                        onClick={() => setSmartSearchQuery('')}
                      >
                        Clear Search
                      </Button>
                    ) : null}
                  </div>

                  <div className="relative mt-3">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
                    <Input
                      value={smartSearchQuery}
                      onChange={(event) => setSmartSearchQuery(event.target.value)}
                      placeholder="Try: online meetings this week where budget was discussed"
                      className="h-11 border-slate-700/70 bg-slate-900/70 pl-9"
                    />
                  </div>

                  <p className="mt-2 text-xs text-slate-400">{smartSearchSummary}</p>

                  <div className="mt-3 flex flex-wrap gap-2">
                    {SMART_SEARCH_SUGGESTIONS.map((preset) => {
                      const isActive = smartSearchQuery.trim().toLowerCase() === preset.query.toLowerCase()
                      return (
                        <button
                          key={preset.label}
                          type="button"
                          onClick={() => setSmartSearchQuery(preset.query)}
                          aria-pressed={isActive}
                          className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                            isActive
                              ? 'border-teal-400/30 bg-teal-500/15 text-teal-200'
                              : 'border-slate-700/70 bg-slate-900/70 text-slate-300 hover:bg-slate-800/80'
                          }`}
                        >
                          {preset.label}
                        </button>
                      )
                    })}
                  </div>

                  {hasSmartSearch && activeSearchFacets.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {activeSearchFacets.map((facet) => (
                        <span key={facet} className="rounded-full border border-slate-700/70 bg-slate-900/70 px-2.5 py-1 text-[11px] font-medium text-slate-300">
                          {facet}
                        </span>
                      ))}
                    </div>
                  ) : null}

                  {hasSmartSearch && topSearchMatches.length ? (
                    <div className="mt-4 grid gap-2 md:grid-cols-3">
                      {topSearchMatches.map(({ meeting, evaluation }) => (
                        <button
                          key={`top-${meeting.id}`}
                          type="button"
                          onClick={() => setSelectedMeeting(meeting)}
                          className="rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2 text-left transition hover:bg-slate-800/80"
                        >
                          <p className="truncate text-xs font-semibold text-white">{meeting.title}</p>
                          <p className="mt-1 text-[11px] text-slate-500">
                            {(evaluation.matchedTokens || []).slice(0, 2).join(', ') || 'semantic match'}
                          </p>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>

                <aside className="rounded-[2rem] border border-slate-700/70 bg-slate-900/70 p-6 shadow-2xl backdrop-blur-xl">
                  <p className="text-sm font-semibold text-white">Dashboard Pulse</p>
                  <p className="mt-1 text-xs text-slate-400">Quick snapshot of current workspace activity.</p>

                  <div className="mt-4 grid grid-cols-2 gap-3">
                    <div className="rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-slate-500">Results</p>
                      <p className="mt-1 text-xl font-semibold text-white">{searchedMeetings.length}</p>
                    </div>
                    <div className="rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-slate-500">Live</p>
                      <p className="mt-1 text-xl font-semibold text-white">{activeRecordings}</p>
                    </div>
                    <div className="rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-slate-500">Online</p>
                      <p className="mt-1 text-xl font-semibold text-white">{onlineMeetings.length}</p>
                    </div>
                    <div className="rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-slate-500">Completed</p>
                      <p className="mt-1 text-xl font-semibold text-white">{notesMeetings.length}</p>
                    </div>
                  </div>

                  <div className="mt-4 rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-3">
                    <p className="text-[11px] uppercase tracking-wide text-slate-500">Latest Activity</p>
                    {latestMeeting ? (
                      <>
                        <p className="mt-1 truncate text-sm font-semibold text-white">{latestMeeting.title}</p>
                        <p className="text-xs text-slate-400">{formatDate(latestMeeting.createdAt)}</p>
                      </>
                    ) : (
                      <p className="mt-1 text-xs text-slate-400">No meetings yet.</p>
                    )}
                  </div>
                </aside>
              </div>

              <Tabs value={activeDashboardTab} onValueChange={setActiveDashboardTab} className="w-full flex-col gap-4">
                <TabsList className="h-11 rounded-2xl border border-slate-700/70 bg-slate-900/70 p-1 backdrop-blur-xl">
                  <TabsTrigger value="overview" className="rounded-lg px-3 text-sm text-slate-400 data-[state=active]:border-slate-600/80 data-[state=active]:bg-slate-800/80 data-[state=active]:text-white">Overview</TabsTrigger>
                  <TabsTrigger value="online" className="rounded-lg px-3 text-sm text-slate-400 data-[state=active]:border-slate-600/80 data-[state=active]:bg-slate-800/80 data-[state=active]:text-white">Online Meetings</TabsTrigger>
                  <TabsTrigger value="offline" className="rounded-lg px-3 text-sm text-slate-400 data-[state=active]:border-slate-600/80 data-[state=active]:bg-slate-800/80 data-[state=active]:text-white">Offline Meetings</TabsTrigger>
                  <TabsTrigger value="notes" className="rounded-lg px-3 text-sm text-slate-400 data-[state=active]:border-slate-600/80 data-[state=active]:bg-slate-800/80 data-[state=active]:text-white">Meeting Notes</TabsTrigger>
                </TabsList>

                <TabsContent value="overview" className="space-y-6">
                  <div className="grid gap-5 xl:grid-cols-[1.45fr_0.95fr]">
                    <section className="relative overflow-hidden rounded-[2rem] border border-slate-700/70 bg-slate-900/70 p-6 shadow-2xl backdrop-blur-xl">
                      <div className="pointer-events-none absolute -left-24 top-10 h-44 w-44 rounded-full bg-teal-500/10 blur-3xl" />
                      <div className="pointer-events-none absolute -right-16 bottom-0 h-40 w-40 rounded-full bg-amber-500/10 blur-3xl" />

                      <div className="relative z-10 flex flex-wrap items-start justify-between gap-4">
                        <div className="min-w-0">
                          <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-teal-300">Mission Snapshot</p>
                          <h3 className="mt-2 font-display text-2xl font-semibold tracking-tight text-white sm:text-3xl">
                            {latestMeeting ? latestMeeting.title : 'No meetings captured yet'}
                          </h3>
                          <p className="mt-2 text-xs text-slate-400">
                            {latestMeeting
                              ? `${formatPlatformLabel(latestMeeting.platform)} | ${formatDate(latestMeeting.createdAt)}`
                              : 'Create your first event to seed this board with live context.'}
                          </p>
                        </div>

                        {latestMeeting ? (
                          <Button
                            variant="outline"
                            size="sm"
                            className="border-slate-600/80 bg-slate-900/70"
                            onClick={() => setSelectedMeeting(latestMeeting)}
                          >
                            Open Latest Notes
                          </Button>
                        ) : null}
                      </div>

                      <div className="relative z-10 mt-5 rounded-2xl border border-slate-600/60 bg-gradient-to-r from-slate-900/90 via-slate-900/80 to-slate-800/70 p-5">
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Executive Brief</p>
                        <p className="mt-3 text-sm leading-relaxed text-slate-100">
                          {shortenText(latestMeeting?.summary, 320)}
                        </p>
                      </div>

                      <div className="relative z-10 mt-5 grid gap-3 sm:grid-cols-2">
                        {recentMeetings.length ? (
                          recentMeetings.slice(0, 4).map((meeting) => (
                            <button
                              key={`snapshot-${meeting.id}`}
                              type="button"
                              onClick={() => setSelectedMeeting(meeting)}
                              className="rounded-xl border border-slate-700/70 bg-slate-900/70 px-4 py-3 text-left transition hover:-translate-y-0.5 hover:bg-slate-800/80"
                            >
                              <p className="truncate text-sm font-semibold text-white">{meeting.title}</p>
                              <p className="mt-1 text-[11px] text-slate-400">
                                {formatPlatformLabel(meeting.platform)} | {meeting.status}
                              </p>
                              <p className="mt-2 line-clamp-2 text-xs text-slate-500">{shortenText(meeting.summary, 120)}</p>
                            </button>
                          ))
                        ) : (
                          <div className="sm:col-span-2 rounded-xl border border-dashed border-slate-700/70 bg-slate-900/60 px-4 py-8 text-center text-sm text-slate-500">
                            Recent decisions will appear here once meetings are captured.
                          </div>
                        )}
                      </div>
                    </section>

                    <aside className="space-y-4">
                      <article className="rounded-[2rem] border border-slate-700/70 bg-slate-900/70 p-5 shadow-2xl backdrop-blur-xl">
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Operational Mix</p>

                        <div className="mt-4 space-y-4">
                          <div>
                            <div className="flex items-center justify-between text-xs text-slate-400">
                              <span>Completion Rate</span>
                              <span>{completionRate}%</span>
                            </div>
                            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800/90">
                              <div className="h-full rounded-full bg-emerald-400" style={{ width: `${Math.max(6, completionRate)}%` }} />
                            </div>
                          </div>

                          <div>
                            <div className="flex items-center justify-between text-xs text-slate-400">
                              <span>Online Mix</span>
                              <span>{onlineMix}%</span>
                            </div>
                            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800/90">
                              <div className="h-full rounded-full bg-amber-400" style={{ width: `${Math.max(6, onlineMix)}%` }} />
                            </div>
                          </div>

                          <div className="rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-3">
                            <p className="text-[11px] uppercase tracking-wide text-slate-500">Live Sessions</p>
                            <p className="mt-1 text-2xl font-semibold text-white">{activeRecordings}</p>
                            <p className="text-xs text-slate-500">Monitoring active capture pipelines now.</p>
                          </div>
                        </div>
                      </article>

                      <article className="rounded-[2rem] border border-slate-700/70 bg-slate-900/70 p-5 shadow-2xl backdrop-blur-xl">
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Focus Queue</p>
                        <p className="mt-2 text-xs text-slate-500">Run one-click smart filters for fast triage.</p>

                        <div className="mt-4 space-y-2">
                          {SMART_SEARCH_SUGGESTIONS.map((preset) => {
                            const isActive = smartSearchQuery.trim().toLowerCase() === preset.query.toLowerCase()
                            return (
                              <button
                                key={`queue-${preset.label}`}
                                type="button"
                                onClick={() => setSmartSearchQuery(preset.query)}
                                className={`w-full rounded-lg border px-3 py-2 text-left text-xs font-medium transition ${
                                  isActive
                                    ? 'border-teal-400/40 bg-teal-500/15 text-teal-200'
                                    : 'border-slate-700/70 bg-slate-900/70 text-slate-300 hover:bg-slate-800/80'
                                }`}
                              >
                                {preset.label}
                              </button>
                            )
                          })}
                        </div>

                        {hasSmartSearch && activeSearchFacets.length ? (
                          <div className="mt-4 flex flex-wrap gap-2">
                            {activeSearchFacets.map((facet) => (
                              <span key={`overview-${facet}`} className="rounded-full border border-slate-700/70 bg-slate-900/70 px-2.5 py-1 text-[11px] font-medium text-slate-300">
                                {facet}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </article>
                    </aside>
                  </div>

                  <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
                    {dashboardStats.map((stat) => (
                      <article key={stat.label} className="relative overflow-hidden rounded-[2rem] border border-slate-700/70 bg-slate-900/70 p-6 shadow-2xl backdrop-blur-xl">
                        <div className="pointer-events-none absolute -right-6 -top-6 h-24 w-24 rounded-full bg-slate-900/70 blur-2xl" />
                        <div className="relative z-10 flex items-start justify-between">
                          <p className="text-[11px] font-bold uppercase tracking-widest text-slate-500">{stat.label}</p>
                          <span className="rounded-xl border border-slate-700/70 bg-slate-800/80 p-2 text-white/80">
                            <stat.icon className="h-4 w-4" />
                          </span>
                        </div>
                        <p className="relative z-10 mt-4 font-display text-4xl font-semibold tracking-tight text-white">{stat.value}</p>
                        <div className="relative z-10 mt-5 h-1.5 overflow-hidden rounded-full bg-slate-800/80">
                          <div
                            className={`h-full rounded-full ${stat.accent}`}
                            style={{ width: `${Math.max(10, Math.round((Number(stat.value) / maxDashboardStat) * 100))}%` }}
                          />
                        </div>
                      </article>
                    ))}
                  </div>

                  {meetingsLoading ? (
                    <div className="flex items-center justify-center rounded-[2rem] border border-slate-700/70 bg-slate-900/70 px-4 py-20 backdrop-blur-md text-sm text-slate-400">
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
                    <div className="flex items-center justify-center rounded-[2rem] border border-slate-700/70 bg-slate-900/70 px-4 py-20 backdrop-blur-md text-sm text-slate-400">
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
                    <div className="flex items-center justify-center rounded-[2rem] border border-slate-700/70 bg-slate-900/70 px-4 py-20 backdrop-blur-md text-sm text-slate-400">
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
                    <div className="flex items-center justify-center rounded-[2rem] border border-slate-700/70 bg-slate-900/70 px-4 py-20 backdrop-blur-md text-sm text-slate-400">
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

      <AnimatePresence>
        {selectedMeeting ? (
          <MeetingNotesPanel
            meeting={selectedMeeting}
            transcripts={transcripts}
            loading={transcriptsLoading}
            onClose={() => setSelectedMeeting(null)}
          />
        ) : null}
      </AnimatePresence>

      {activeRecordings > 0 ? (
        <div className="pointer-events-none fixed bottom-4 right-4 flex items-center gap-2 rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-lg shadow-emerald-300/60">
          <Mic className="h-3.5 w-3.5" />
          {activeRecordings} recording {activeRecordings > 1 ? 'sessions' : 'session'} running
        </div>
      ) : null}
    </div>
  )
}



