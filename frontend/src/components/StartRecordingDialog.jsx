import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Loader2, Mic, Plus, Video } from 'lucide-react'
import { startRecording } from '@/lib/api'
import { supabase } from '@/lib/supabase'

const MAX_TITLE_LENGTH = 120
const MAX_LANGUAGE_LENGTH = 40
const MAX_OFFLINE_DETAILS_LENGTH = 2200
const MAX_SPEAKER_NOTES_LENGTH = 5000
const MAX_TRANSCRIPT_ROWS = 250
const PLATFORM_SCHEMA_ERROR_TEXT = "could not find the 'platform' column of 'meetings' in the schema cache"

const PLATFORM_HOST_RULES = {
  meet: ['meet.google.com'],
  teams: ['teams.microsoft.com'],
  zoom: ['zoom.us'],
}

const GOOGLE_MEET_CODE_REGEX = /^[a-z]{3}-[a-z]{4}-[a-z]{3}$/i

function toFriendlyError(message) {
  if (!message) return 'Failed to create meeting event.'
  const normalized = message.toLowerCase()
  if (normalized.includes('network')) return 'Network issue while saving. Please retry.'
  if (normalized.includes('does not match selected platform')) {
    return 'The link does not match selected platform. For Google Meet, paste full link or meeting code like cyo-qfpw-fir.'
  }
  if (normalized.includes(PLATFORM_SCHEMA_ERROR_TEXT)) {
    return "Supabase schema is missing meetings.platform. Run: ALTER TABLE public.meetings ADD COLUMN platform text DEFAULT 'meet';"
  }
  return message
}

function isPlatformSchemaError(error) {
  const combined = `${error?.message || ''} ${error?.details || ''}`.toLowerCase()
  return combined.includes(PLATFORM_SCHEMA_ERROR_TEXT)
}

function normalizeOnlineMeetingUrl(rawUrl, platform) {
  const trimmed = (rawUrl || '').trim()
  if (!trimmed) return trimmed

  if (platform === 'meet' && GOOGLE_MEET_CODE_REGEX.test(trimmed)) {
    return `https://meet.google.com/${trimmed}`
  }

  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed
  }

  return `https://${trimmed}`
}

function validateOnlineMeetingUrl(rawUrl, platform) {
  let parsed
  try {
    parsed = new URL(normalizeOnlineMeetingUrl(rawUrl, platform))
  } catch {
    throw new Error('Please enter a valid meeting URL.')
  }

  if (parsed.protocol !== 'https:') {
    throw new Error('Only HTTPS meeting links are allowed.')
  }

  const host = (parsed.hostname || '').toLowerCase()
  const allowedHosts = PLATFORM_HOST_RULES[platform] || []
  const isAllowedHost = allowedHosts.some((allowedHost) => host === allowedHost || host.endsWith(`.${allowedHost}`))

  if (!isAllowedHost) {
    const label = platform === 'meet' ? 'Google Meet' : platform === 'teams' ? 'Microsoft Teams' : 'Zoom'
    throw new Error(`URL does not match selected platform (${label}).`)
  }

  parsed.hash = ''
  return parsed.toString()
}

function buildOfflineTranscriptRows(rawSpeakerNotes, meetingId) {
  const lines = rawSpeakerNotes
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, MAX_TRANSCRIPT_ROWS)

  return lines.map((line, index) => {
    const separator = line.indexOf(':')
    const speakerName = separator > 0 ? line.slice(0, separator).trim() : 'Participant'
    const spokenText = separator > 0 ? line.slice(separator + 1).trim() : line

    return {
      meeting_id: meetingId,
      speaker_name: (speakerName || 'Participant').slice(0, 80),
      spoken_text: (spokenText || line).slice(0, 500),
      start_time_seconds: index * 15,
    }
  })
}

export function StartRecordingDialog({
  onCreated,
  triggerLabel = 'Create Event',
  floating = false,
}) {
  const [open, setOpen] = useState(false)
  const [meetingType, setMeetingType] = useState('online')
  const [title, setTitle] = useState('')
  const [platform, setPlatform] = useState('meet')
  const [language, setLanguage] = useState('Auto')
  const [url, setUrl] = useState('')
  const [offlineDetails, setOfflineDetails] = useState('')
  const [speakerNotes, setSpeakerNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const isOnline = meetingType === 'online'

  const resetForm = () => {
    setMeetingType('online')
    setTitle('')
    setPlatform('meet')
    setLanguage('Auto')
    setUrl('')
    setOfflineDetails('')
    setSpeakerNotes('')
    setError('')
  }

  const handleDialogChange = (nextOpen) => {
    setOpen(nextOpen)
    if (!nextOpen) resetForm()
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setLoading(true)
    setError('')

    const normalizedTitle = (title.trim() || 'Untitled Meeting').slice(0, MAX_TITLE_LENGTH)
    const normalizedLanguage = ((language || 'Auto').trim() || 'Auto').slice(0, MAX_LANGUAGE_LENGTH)

    try {
      if (isOnline) {
        if (!url.trim()) throw new Error('Meeting link is required for online meetings.')
        const safeMeetingUrl = validateOnlineMeetingUrl(url, platform)

        await startRecording({
          title: normalizedTitle,
          platform,
          language: normalizedLanguage,
          url: safeMeetingUrl,
        })

        onCreated?.({
          meetingType: 'online',
          title: normalizedTitle,
          message: 'Meeting assistant join request sent. Admit it when prompted in the call.',
        })
      } else {
        const safeOfflineDetails = offlineDetails.trim().slice(0, MAX_OFFLINE_DETAILS_LENGTH)
        const safeSpeakerNotes = speakerNotes.slice(0, MAX_SPEAKER_NOTES_LENGTH)

        const formattedSummary = safeOfflineDetails
          ? `Offline meeting details:\n${safeOfflineDetails}`
          : 'Offline meeting was added manually.'

        let meetingRow = null
        let meetingError = null

        const insertWithPlatform = await supabase
          .from('meetings')
          .insert({
            title: normalizedTitle,
            platform: 'offline',
            language: normalizedLanguage,
            status: 'completed',
            summary: formattedSummary,
          })
          .select('*')
          .single()

        meetingRow = insertWithPlatform.data
        meetingError = insertWithPlatform.error

        if (meetingError && isPlatformSchemaError(meetingError)) {
          const insertWithoutPlatform = await supabase
            .from('meetings')
            .insert({
              title: normalizedTitle,
              language: normalizedLanguage,
              status: 'completed',
              summary: formattedSummary,
            })
            .select('*')
            .single()

          meetingRow = insertWithoutPlatform.data
          meetingError = insertWithoutPlatform.error
        }

        if (meetingError) throw meetingError

        const transcriptRows = buildOfflineTranscriptRows(safeSpeakerNotes, meetingRow.id)
        if (transcriptRows.length > 0) {
          const { error: transcriptError } = await supabase
            .from('transcripts')
            .insert(transcriptRows)

          if (transcriptError) throw transcriptError
        }

        onCreated?.({
          meetingType: 'offline',
          title: normalizedTitle,
          message: 'Offline meeting saved to Supabase.',
        })
      }

      setOpen(false)
      resetForm()
    } catch (submitError) {
      setError(toFriendlyError(submitError?.message))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleDialogChange}>
      <DialogTrigger asChild>
        {floating ? (
          <button
            className="group fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full bg-indigo-600 shadow-xl shadow-indigo-500/25 transition-all duration-200 hover:bg-indigo-500 hover:scale-105"
            aria-label="Create meeting event"
          >
            <Video className="mx-auto h-6 w-6 text-white" />
          </button>
        ) : (
          <Button className="h-10 bg-indigo-600 px-4 font-semibold text-white hover:bg-indigo-500">
            <Plus className="mr-1 h-4 w-4" />
            {triggerLabel}
          </Button>
        )}
      </DialogTrigger>

      <DialogContent className="sm:max-w-[560px] border border-neutral-200 bg-white p-0">
        <DialogHeader className="border-b border-neutral-200 px-6 py-5">
          <DialogTitle className="flex items-center gap-2 text-lg font-semibold text-neutral-900">
            <Mic className="h-4 w-4 text-indigo-600" />
            Create Meeting Event
          </DialogTitle>
          <DialogDescription className="text-sm text-neutral-600">
            Choose online or offline meeting. Online meetings will trigger the bot to request entry automatically.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 px-6 py-5">
          <div className="grid gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Meeting Type</label>
            <Select value={meetingType} onValueChange={setMeetingType}>
              <SelectTrigger className="h-10 border-neutral-200 bg-neutral-50">
                <SelectValue placeholder="Select type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="online">Online</SelectItem>
                <SelectItem value="offline">Offline</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Topic / Meeting Name</label>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Enter meeting topic"
              className="h-10 border-neutral-200 bg-neutral-50"
              maxLength={MAX_TITLE_LENGTH}
              required
            />
          </div>

          <div className="grid gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Preferred Language</label>
            <Input
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              placeholder="Auto (supports mixed languages)"
              className="h-10 border-neutral-200 bg-neutral-50"
              maxLength={MAX_LANGUAGE_LENGTH}
            />
          </div>

          {isOnline ? (
            <>
              <div className="grid gap-1.5">
                <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Online Platform</label>
                <Select value={platform} onValueChange={setPlatform}>
                  <SelectTrigger className="h-10 border-neutral-200 bg-neutral-50">
                    <SelectValue placeholder="Select platform" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="meet">Google Meet</SelectItem>
                    <SelectItem value="teams">Microsoft Teams</SelectItem>
                    <SelectItem value="zoom">Zoom</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="grid gap-1.5">
                <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Meeting Link</label>
                <Input
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder="https://meet.google.com/..."
                  className="h-10 border-neutral-200 bg-neutral-50"
                  autoComplete="off"
                  required
                />
              </div>

              <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs text-indigo-700">
                Your meeting assistant will request access automatically after creation.
              </div>
            </>
          ) : (
            <>
              <div className="grid gap-1.5">
                <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Offline Meeting Details</label>
                <textarea
                  value={offlineDetails}
                  onChange={(event) => setOfflineDetails(event.target.value)}
                  placeholder="Agenda, location, attendees, and context"
                  maxLength={MAX_OFFLINE_DETAILS_LENGTH}
                  className="min-h-24 rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-800 outline-none focus:border-indigo-400"
                />
              </div>

              <div className="grid gap-1.5">
                <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Who Spoke What (Optional)</label>
                <textarea
                  value={speakerNotes}
                  onChange={(event) => setSpeakerNotes(event.target.value)}
                  placeholder={"Example:\nAman: Finalize proposal today\nRiya: Share budget updates by 5 PM"}
                  maxLength={MAX_SPEAKER_NOTES_LENGTH}
                  className="min-h-28 rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-800 outline-none focus:border-indigo-400"
                />
              </div>
            </>
          )}

          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          ) : null}

          <DialogFooter className="border-t border-neutral-200 pt-4">
            <Button type="button" variant="outline" onClick={() => setOpen(false)} className="h-10 border-neutral-300">
              Cancel
            </Button>
            <Button type="submit" disabled={loading} className="h-10 bg-indigo-600 font-semibold text-white hover:bg-indigo-500">
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                'Create Event'
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}