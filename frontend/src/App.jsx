import { useEffect, useState } from 'react'
import { supabase } from './lib/supabase'
import { TooltipProvider } from '@/components/ui/tooltip'
import { DashboardLayout } from '@/components/watermelon/meetings-dashboard/dashboardLayout'
import { MeetingCard } from '@/components/watermelon/meetings-dashboard/components/MeetingCard'
import { SidebarFilters } from '@/components/watermelon/meetings-dashboard/components/SidebarFilters'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  IconCalendarEvent, IconFilter, IconSearch, IconColumns,
  IconLayoutGrid, IconCalendar, IconPlus
} from '@tabler/icons-react'
import { Activity, X, Mic } from 'lucide-react'

// ─── Column definitions matching our Supabase status values ──────────────────
const MEETING_COLUMNS = [
  { id: 'recording', title: 'Live 🔴', colorClass: 'bg-red-50 text-red-500 border-red-100' },
  { id: 'completed', title: 'Completed ✅', colorClass: 'bg-green-50 text-green-600 border-green-100' },
]

// ─── Map Supabase row → Watermelon MeetingCard shape ─────────────────────────
function toCard(m) {
  return {
    id: m.id,
    columnId: m.status === 'recording' ? 'recording' : 'completed',
    title: m.title || 'Untitled Meeting',
    platform: 'meet',
    date: new Date(m.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
    host: { name: 'Smart Notes Bot', avatar: '' },
    duration: m.language || 'English',
    relatedTo: m.summary ? m.summary.substring(0, 45) + '…' : 'Processing transcript…',
    // Our custom fields passed through
    _summary: m.summary,
    _language: m.language,
    _status: m.status,
    _raw: m,
  }
}

// ─── Transcript Side Panel ────────────────────────────────────────────────────
function TranscriptPanel({ meeting, onClose }) {
  const [transcripts, setTranscripts] = useState([])

  useEffect(() => {
    if (!meeting) { setTranscripts([]); return }
    supabase.from('transcripts')
      .select('*')
      .eq('meeting_id', meeting._raw.id)
      .order('start_time_seconds', { ascending: true })
      .then(({ data }) => setTranscripts(data || []))

    const sub = supabase.channel(`tx-${meeting._raw.id}`)
      .on('postgres_changes', {
        event: 'INSERT', schema: 'public', table: 'transcripts',
        filter: `meeting_id=eq.${meeting._raw.id}`
      }, payload => setTranscripts(prev => [...prev, payload.new]))
      .subscribe()

    return () => supabase.removeChannel(sub)
  }, [meeting])

  if (!meeting) return null

  return (
    <div className="fixed inset-y-0 right-0 w-[420px] bg-white border-l border-neutral-200 flex flex-col shadow-2xl z-50">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-neutral-200 shrink-0">
        <div className="flex items-center gap-2 overflow-hidden">
          <Mic className="size-4 text-indigo-500 shrink-0" />
          <h2 className="font-semibold text-sm text-neutral-800 truncate">{meeting.title}</h2>
          {meeting._status === 'recording' && (
            <span className="flex items-center gap-1 bg-red-100 text-red-600 text-[10px] px-2 py-0.5 rounded-full font-semibold shrink-0 animate-pulse">
              ● Live
            </span>
          )}
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-neutral-100 text-neutral-400 transition-colors">
          <X className="size-4" />
        </button>
      </div>

      {/* AI Summary */}
      {meeting._summary && (
        <div className="px-5 py-4 border-b border-neutral-200 shrink-0 bg-indigo-50/60">
          <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-500 mb-2 flex items-center gap-1.5">
            <Activity className="size-3" /> AI Summary
          </p>
          <p className="text-xs text-neutral-600 leading-relaxed">{meeting._summary}</p>
        </div>
      )}

      {/* Transcript bubbles */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {transcripts.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-neutral-400 gap-3">
            <Activity className="size-8 opacity-20" />
            <p className="text-sm font-medium">No transcript yet</p>
            <p className="text-xs text-center opacity-70 leading-relaxed">
              Run <code className="bg-neutral-100 px-1.5 py-0.5 rounded text-neutral-600">python app.py</code><br/>to start recording this meeting.
            </p>
          </div>
        ) : transcripts.map((t, idx) => {
          const isBot = t.speaker_name === 'Meeting Host' || t.speaker_name === 'Bot'
          return (
            <div key={t.id || idx} className={`flex flex-col ${isBot ? 'items-end' : 'items-start'}`}>
              <span className="text-[10px] text-neutral-400 mb-1 font-medium px-1">
                {t.speaker_name} · {new Date(t.start_time_seconds * 1000).toISOString().substr(14, 5)}
              </span>
              <div className={`max-w-[85%] px-3.5 py-2.5 rounded-2xl text-[13px] leading-relaxed shadow-sm ${
                isBot
                  ? 'bg-indigo-600 text-white rounded-tr-sm'
                  : 'bg-neutral-100 text-neutral-700 rounded-tl-sm border border-neutral-200/60'
              }`}>
                {t.spoken_text}
              </div>
            </div>
          )
        })}
      </div>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-neutral-200 shrink-0 bg-neutral-50">
        <p className="text-[10px] text-neutral-400 text-center">
          Language: <span className="font-medium text-neutral-600">{meeting._language}</span>
          &nbsp;·&nbsp;{transcripts.length} segments
        </p>
      </div>
    </div>
  )
}

// ─── Meetings Kanban Board ────────────────────────────────────────────────────
function MeetingsBoard({ meetings, onSelectMeeting }) {
  const [showFilters, setShowFilters] = useState(true)

  const columnsWithCounts = MEETING_COLUMNS.map(col => ({
    ...col,
    count: meetings.filter(m => m.columnId === col.id).length,
    cards: meetings.filter(m => m.columnId === col.id),
  }))

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <header className="h-12 flex items-center justify-between border-b-[1.5px] border-neutral-200 shrink-0">
        <div className="flex items-center gap-1.5">
          <IconCalendarEvent className="size-5 text-neutral-500" strokeWidth={1.5} />
          <h1 className="text-sm font-semibold tracking-tight text-neutral-700">Meetings</h1>
        </div>
        {/* Mobile filter sheet */}
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="size-8 text-neutral-500 lg:hidden outline-none focus-visible:ring-0">
              <IconFilter className="size-4" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="p-2 w-[280px]">
            <SheetHeader className="px-2 py-4 border-b">
              <SheetTitle className="text-sm font-semibold">Filters</SheetTitle>
            </SheetHeader>
            <div className="mt-2 overflow-y-auto"><SidebarFilters /></div>
          </SheetContent>
        </Sheet>
      </header>

      <main className="flex gap-2 flex-1 overflow-hidden pt-4 lg:pt-5">
        {/* Desktop sidebar filters */}
        {showFilters && <div className="hidden lg:flex"><SidebarFilters /></div>}

        <div className="flex-1 flex flex-col min-w-0">
          {/* Toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <Button variant="outline" onClick={() => setShowFilters(v => !v)}
              className="h-9 gap-1.5 text-neutral-600 bg-white border-[1.3px] border-neutral-200 px-2.5 tracking-tight shadow-none outline-none focus-visible:ring-0">
              <IconFilter className="w-4 h-4 text-neutral-400" />
              {showFilters ? 'Hide Filters' : 'Show Filters'}
            </Button>

            <div className="flex items-center gap-2">
              <Tabs defaultValue="kanban" className="w-auto">
                <TabsList className="h-8 p-0 bg-neutral-100 border-none shadow-none">
                  <TabsTrigger value="kanban" className="h-full w-9 p-0 data-[state=active]:bg-white outline-none focus-visible:ring-0">
                    <IconColumns className="size-4" strokeWidth={2} />
                  </TabsTrigger>
                  <TabsTrigger value="grid" className="h-full w-9 p-0 data-[state=active]:bg-white outline-none focus-visible:ring-0">
                    <IconLayoutGrid className="size-4" strokeWidth={2} />
                  </TabsTrigger>
                  <TabsTrigger value="calendar" className="h-full w-9 p-0 data-[state=active]:bg-white outline-none focus-visible:ring-0">
                    <IconCalendar className="size-4" strokeWidth={2} />
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              <div className="relative">
                <IconSearch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" />
                <Input placeholder="Search meetings…" className="h-9 pl-9 w-[200px] bg-white border-neutral-200 border-[1.3px] focus-visible:ring-0 shadow-none text-sm" />
              </div>
            </div>
          </div>

          {/* Kanban columns */}
          <div className="flex-1 overflow-hidden">
            <div className="flex gap-3 h-full w-full overflow-x-auto pb-4">
              {columnsWithCounts.map(column => (
                <div key={column.id}
                  className="flex-none w-[300px] lg:flex-1 flex flex-col gap-2.5 min-h-0 border-[1.3px] border-neutral-200 rounded-xl p-2 bg-neutral-50/50">

                  {/* Column header */}
                  <div className="flex items-center justify-between px-1 pt-0.5 shrink-0">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className={`h-6 rounded-full px-2.5 text-[11px] font-semibold border-[1.3px] ${column.colorClass}`}>
                        {column.title}
                      </Badge>
                      <span className="flex items-center justify-center size-5 bg-neutral-200 text-neutral-600 rounded-full text-[10px] font-bold">
                        {column.count}
                      </span>
                    </div>
                    <button className="size-6 text-neutral-400 bg-white border border-neutral-200 hover:bg-neutral-100 rounded flex items-center justify-center transition-colors">
                      <IconPlus className="size-3.5" />
                    </button>
                  </div>

                  {/* Cards */}
                  <div className="flex-1 overflow-y-auto space-y-2 pr-0.5">
                    {column.cards.map(meeting => (
                      <div key={meeting.id} onClick={() => onSelectMeeting(meeting)} className="cursor-pointer transition-opacity hover:opacity-90">
                        <MeetingCard meeting={meeting} />
                      </div>
                    ))}

                    {column.cards.length === 0 && (
                      <div className="flex flex-col items-center justify-center py-12 text-neutral-300 gap-2">
                        <Mic className="size-6" />
                        <p className="text-xs font-medium">No meetings here yet</p>
                        {column.id === 'recording' && (
                          <p className="text-[10px] text-center opacity-80 px-4">Run app.py to start a live session</p>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

// ─── Root App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [meetings, setMeetings] = useState([])
  const [selectedMeeting, setSelectedMeeting] = useState(null)

  useEffect(() => {
    // Initial load
    supabase.from('meetings').select('*').order('created_at', { ascending: false })
      .then(({ data }) => setMeetings((data || []).map(toCard)))

    // Realtime subscription
    const sub = supabase.channel('meetings-realtime')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'meetings' }, payload => {
        if (!payload.new) return
        const card = toCard(payload.new)
        setMeetings(prev => {
          const exists = prev.find(m => m.id === card.id)
          return exists ? prev.map(m => m.id === card.id ? card : m) : [card, ...prev]
        })
        // Keep selected meeting in sync if it's the one that changed
        setSelectedMeeting(prev => prev?.id === card.id ? card : prev)
      }).subscribe()

    return () => supabase.removeChannel(sub)
  }, [])

  return (
    <TooltipProvider>
      <div className={`relative transition-all duration-300 ${selectedMeeting ? 'pr-[420px]' : ''}`}>
        <DashboardLayout>
          <MeetingsBoard meetings={meetings} onSelectMeeting={setSelectedMeeting} />
        </DashboardLayout>
        <TranscriptPanel meeting={selectedMeeting} onClose={() => setSelectedMeeting(null)} />
      </div>
    </TooltipProvider>
  )
}
