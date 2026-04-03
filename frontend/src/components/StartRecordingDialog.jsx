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
import { listRecordings, startRecording, stopRecording } from '@/lib/api'

const MAX_TITLE_LENGTH = 120
const MAX_LANGUAGE_LENGTH = 40
const OFFLINE_STATUS_POLL_INTERVAL_MS = 2000
const OFFLINE_STATUS_POLL_ATTEMPTS = 120

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
  return message
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

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
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
  const [offlineRecordingId, setOfflineRecordingId] = useState('')
  const [offlineTranscribing, setOfflineTranscribing] = useState(false)
  const [offlineStateMessage, setOfflineStateMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const isOnline = meetingType === 'online'
  const isOfflineRecordingActive = !!offlineRecordingId
  const isDialogLocked = isOfflineRecordingActive || offlineTranscribing

  const resetForm = () => {
    setMeetingType('online')
    setTitle('')
    setPlatform('meet')
    setLanguage('Auto')
    setUrl('')
    setOfflineRecordingId('')
    setOfflineTranscribing(false)
    setOfflineStateMessage('')
    setError('')
  }

  const handleDialogChange = (nextOpen) => {
    if (!nextOpen && isDialogLocked) {
      setError('Stop and complete the current offline recording before closing this dialog.')
      return
    }

    setOpen(nextOpen)
    if (!nextOpen) resetForm()
  }

  const handleMeetingTypeChange = (nextMeetingType) => {
    if (!isOnline && isDialogLocked && nextMeetingType !== 'offline') {
      setError('Stop the active offline recording before switching meeting type.')
      return
    }
    setMeetingType(nextMeetingType)
    setError('')
  }

  const getNormalizedMeetingData = () => {
    const normalizedTitle = (title.trim() || 'Untitled Meeting').slice(0, MAX_TITLE_LENGTH)
    const normalizedLanguage = ((language || 'Auto').trim() || 'Auto').slice(0, MAX_LANGUAGE_LENGTH)
    return { normalizedTitle, normalizedLanguage }
  }

  const waitForOfflineCompletion = async (recordingId) => {
    for (let attempt = 0; attempt < OFFLINE_STATUS_POLL_ATTEMPTS; attempt += 1) {
      const sessions = await listRecordings()
      const session = (sessions || []).find((entry) => entry.id === recordingId)

      if (session) {
        const status = (session.status || '').toLowerCase()
        if (status === 'completed' || status === 'error') {
          return session
        }
      }

      await wait(OFFLINE_STATUS_POLL_INTERVAL_MS)
    }

    throw new Error('Transcription is taking longer than expected. Keep dashboard open and check notes shortly.')
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!isOnline) return

    setLoading(true)
    setError('')

    const { normalizedTitle, normalizedLanguage } = getNormalizedMeetingData()

    try {
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

      setOpen(false)
      resetForm()
    } catch (submitError) {
      setError(toFriendlyError(submitError?.message))
    } finally {
      setLoading(false)
    }
  }

  const handleStartOfflineRecording = async () => {
    setError('')
    setLoading(true)

    const { normalizedTitle, normalizedLanguage } = getNormalizedMeetingData()

    try {
      const response = await startRecording({
        title: normalizedTitle,
        platform: 'local',
        language: normalizedLanguage,
        manual_stop: true,
      })

      setOfflineRecordingId(response.recording_id)
      setOfflineStateMessage('Recording started. Speak now and click Stop Recording when you are done.')
    } catch (startError) {
      setError(toFriendlyError(startError?.message))
    } finally {
      setLoading(false)
    }
  }

  const handleStopOfflineRecording = async () => {
    if (!offlineRecordingId) return

    setError('')
    setLoading(true)
    setOfflineTranscribing(true)
    setOfflineStateMessage('Stopping recording. Transcription will begin in a few seconds...')

    const { normalizedTitle } = getNormalizedMeetingData()

    try {
      await stopRecording(offlineRecordingId)
    } catch (stopError) {
      setError(toFriendlyError(stopError?.message))
      setLoading(false)
      setOfflineTranscribing(false)
      return
    }

    setOfflineStateMessage('Recording stopped. Transcribing audio and preparing notes...')

    try {
      const finalSession = await waitForOfflineCompletion(offlineRecordingId)
      if ((finalSession?.status || '').toLowerCase() === 'error') {
        throw new Error(finalSession?.error || 'Offline recording failed to process.')
      }

      onCreated?.({
        meetingType: 'offline',
        title: normalizedTitle,
        message: 'Offline recording completed. Notes are ready.',
      })

      setOpen(false)
      resetForm()
    } catch (processingError) {
      setError(toFriendlyError(processingError?.message))
      setOfflineRecordingId('')
      setOfflineStateMessage('')
    } finally {
      setLoading(false)
      setOfflineTranscribing(false)
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
            Choose online or offline meeting. Offline mode records your voice, then transcribes automatically after stop.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 px-6 py-5">
          <div className="grid gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wide text-neutral-600">Meeting Type</label>
            <Select value={meetingType} onValueChange={handleMeetingTypeChange}>
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
              <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs text-indigo-700">
                Voice command flow: Start recording, speak naturally, then Stop recording to trigger transcription.
              </div>

              {offlineStateMessage ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                  {offlineStateMessage}
                </div>
              ) : null}
            </>
          )}

          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          ) : null}

          <DialogFooter className="border-t border-neutral-200 pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
              className="h-10 border-neutral-300"
              disabled={loading || isDialogLocked}
            >
              Cancel
            </Button>

            {isOnline ? (
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
            ) : offlineTranscribing ? (
              <Button type="button" disabled className="h-10 bg-indigo-600 font-semibold text-white">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Transcribing...
              </Button>
            ) : isOfflineRecordingActive ? (
              <Button
                type="button"
                onClick={handleStopOfflineRecording}
                disabled={loading}
                className="h-10 bg-rose-600 font-semibold text-white hover:bg-rose-500"
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Stopping...
                  </>
                ) : (
                  'Stop Recording'
                )}
              </Button>
            ) : (
              <Button
                type="button"
                onClick={handleStartOfflineRecording}
                disabled={loading}
                className="h-10 bg-indigo-600 font-semibold text-white hover:bg-indigo-500"
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Starting...
                  </>
                ) : (
                  'Start Voice Recording'
                )}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}