import re

with open('src/App.jsx', 'r', encoding='utf-8') as f:
    text = f.read()

# Replace the entire AuthScreen return
auth_return_pattern = re.compile(r'return \(\s*<div className="flex min-h-screen items-center justify-center.+?</form>\s*</div>\s*</div>\s*\)', re.DOTALL)

auth_replacement = '''return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a] text-white px-4 py-10 selection:bg-sky-500/30">
      <div className="pointer-events-none fixed -left-[10%] -top-[10%] h-[40vw] w-[40vw] rounded-full bg-blue-900/10 blur-[100px] mix-blend-screen" />
      <div className="pointer-events-none fixed -right-[5%] bottom-[10%] h-[30vw] w-[30vw] rounded-full bg-indigo-900/10 blur-[100px] mix-blend-screen" />
      <div className="relative w-full max-w-[440px] rounded-[2rem] border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-xl">
        <div className="mb-8">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-white/10 text-sky-400 mb-4">
            <Sparkles className="h-5 w-5" />
          </div>
          <h1 className="text-3xl font-medium tracking-tight text-white mb-2">OceanLabs</h1>
          <p className="text-base font-light text-white/50">Sign in to your intelligent workspace.</p>
        </div>

        {error ? <div className="mb-6 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">{error}</div> : null}
        {notice ? <div className="mb-6 rounded-xl border border-sky-500/20 bg-sky-500/10 px-4 py-3 text-sm text-sky-400">{notice}</div> : null}

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'signup' && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium uppercase tracking-wider text-white/50">Full Name</label>
              <Input required value={fullName} onChange={(e) => setFullName(e.target.value)} className="h-12 border-white/10 bg-white/5 text-white placeholder:text-white/20 focus-visible:ring-sky-500/50" />
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-medium uppercase tracking-wider text-white/50">Email</label>
            <Input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="h-12 border-white/10 bg-white/5 text-white placeholder:text-white/20 focus-visible:ring-sky-500/50" />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium uppercase tracking-wider text-white/50">Password</label>
            <Input required type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-12 border-white/10 bg-white/5 text-white placeholder:text-white/20 focus-visible:ring-sky-500/50" />
          </div>

          <Button type="submit" disabled={loading} className="mt-2 h-12 w-full rounded-xl bg-white text-black font-medium hover:bg-white/90">
            {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : mode === 'login' ? 'Sign In' : 'Create Account'}
          </Button>

          <p className="mt-6 text-center text-sm font-light text-white/50">
            {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
            <button type="button" onClick={() => setMode(mode === 'login' ? 'signup' : 'login')} className="font-medium text-sky-400 hover:text-sky-300">
              {mode === 'login' ? 'Sign up' : 'Sign in'}
            </button>
          </p>
        </form>
      </div>
    </div>
  )'''

text = auth_return_pattern.sub(auth_replacement, text)

app_return_pattern = re.compile(r'return \(\s*<div className="min-h-screen bg-\[.+?(?=\n\s*function HeroPage)', re.DOTALL)

app_replacement = '''return (
    <div className="min-h-screen bg-[#0a0a0a] text-white selection:bg-sky-500/30 font-sans">
      <div className="pointer-events-none fixed inset-0 flex items-center justify-center mix-blend-screen">
        <div className="absolute top-[-20%] left-[-10%] h-[60vw] w-[60vw] rounded-full bg-blue-500/5 blur-[150px]" />
        <div className="absolute bottom-[-10%] right-[-10%] h-[50vw] w-[50vw] rounded-full bg-indigo-500/10 blur-[150px]" />
      </div>

      <div className="relative mx-auto flex min-h-screen max-w-[1600px] z-10">
        <aside className="hidden w-[280px] shrink-0 flex-col border-r border-white/10 bg-white/[0.02] px-6 py-8 backdrop-blur-xl md:flex">
          <div>
            <div className="mb-6 inline-flex items-center justify-center rounded-xl bg-white/10 p-2.5 text-sky-400">
                <Sparkles className="h-5 w-5" />
            </div>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-white/50">OceanLabs</p>
            <p className="mt-1 text-xl font-medium text-white tracking-tight">Intelligence</p>
          </div>

          <nav className="mt-10 space-y-3">
            <button
              onClick={() => setActiveSection('dashboard')}
              className={w-full rounded-xl px-4 py-3 text-left text-sm font-medium transition-all }
            >
              Dashboard
            </button>
            <button
              onClick={() => setActiveSection('settings')}
              className={w-full rounded-xl px-4 py-3 text-left text-sm font-medium transition-all }
            >
              Settings
            </button>
          </nav>

          <div className="mt-auto">
            <div className="mb-6 rounded-2xl border border-white/10 bg-black/20 p-4 text-xs font-light leading-relaxed text-white/50 backdrop-blur-md">
              <div className="mb-2 flex items-center gap-2">
                 <div className="h-2 w-2 rounded-full bg-emerald-400/80 shadow-[0_0_10px_rgba(52,211,153,0.5)] animate-pulse" />
                 <span className="font-medium text-white/90">System Active</span>
              </div>
              Ready to capture online meetings and process audio.
            </div>
            <Button variant="outline" className="h-12 w-full rounded-xl border-white/10 bg-transparent text-white/50 hover:bg-white/10 hover:text-white" onClick={handleSignOut}>
              Sign Out
            </Button>
          </div>
        </aside>

        <main className={lex-1 overflow-x-hidden p-6 md:p-10 }>
          <header className="mb-8 flex flex-wrap items-end justify-between gap-4 border-b border-white/10 pb-6">
            <div>
              <h1 className="text-4xl font-medium tracking-tight text-white mb-2">
                {activeSection === 'dashboard' ? 'Overview' : 'Settings'}
              </h1>
              <p className="text-base font-light text-white/50">Signed in as {session.user.email}</p>
            </div>
            {activeSection === 'dashboard' && (
              <StartRecordingDialog onCreated={handleCreatedMeeting} triggerLabel="New Event" />
            )}
          </header>

          {toastMessage && (
            <div className="mb-6 rounded-2xl border border-sky-500/20 bg-sky-500/10 px-5 py-4 text-sm font-medium text-sky-400 backdrop-blur-md">
              {toastMessage}
            </div>
          )}

          {activeSection === 'settings' ? (
            <SettingsView session={session} />
          ) : (
            <div className="space-y-6 animate-in fade-in duration-700">
              <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl shadow-2xl">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-lg font-medium tracking-tight flex items-center gap-2">
                    <Search className="h-5 w-5 text-sky-400" /> Smart Search
                  </h2>
                  {hasSmartSearch && (
                    <Button variant="ghost" size="sm" className="h-8 text-xs text-white/50 hover:text-white" onClick={() => setSmartSearchQuery('')}>
                      Clear
                    </Button>
                  )}
                </div>
                <div className="relative">
                  <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-white/30" />
                  <Input 
                    value={smartSearchQuery} 
                    onChange={(e) => setSmartSearchQuery(e.target.value)}
                    placeholder="Search by topic, date, or platform..." 
                    className="h-14 rounded-2xl border border-white/10 bg-black/20 pl-12 text-lg font-light text-white placeholder:text-white/30 focus-visible:border-sky-500/30 focus-visible:ring-0" 
                  />
                </div>
              </div>

              <Tabs value={activeDashboardTab} onValueChange={setActiveDashboardTab} className="mt-8">
                <TabsList className="mb-6 flex h-14 w-fit justify-start space-x-1 rounded-2xl border border-white/10 bg-black/20 p-1 backdrop-blur-md overflow-x-auto">
                  <TabsTrigger value="overview" className="rounded-xl px-6 py-2.5 text-sm font-medium data-[state=active]:bg-white/10 data-[state=active]:border data-[state=active]:border-white/20 data-[state=active]:text-white data-[state=active]:shadow-lg text-white/50 transition-all">Overview</TabsTrigger>
                  <TabsTrigger value="online" className="rounded-xl px-6 py-2.5 text-sm font-medium data-[state=active]:bg-white/10 data-[state=active]:border data-[state=active]:border-white/20 data-[state=active]:text-white data-[state=active]:shadow-lg text-white/50 transition-all">Online Sessions</TabsTrigger>
                  <TabsTrigger value="offline" className="rounded-xl px-6 py-2.5 text-sm font-medium data-[state=active]:bg-white/10 data-[state=active]:border data-[state=active]:border-white/20 data-[state=active]:text-white data-[state=active]:shadow-lg text-white/50 transition-all">Offline Notes</TabsTrigger>
                </TabsList>

                <TabsContent value="overview" className="space-y-6 focus-visible:outline-none">
                  <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
                    {dashboardStats.map((stat) => (
                      <div key={stat.label} className="rounded-[2rem] border border-white/10 bg-white/5 p-6 backdrop-blur-xl hover:bg-white/[0.07] transition-colors">
                        <p className="text-sm font-medium tracking-wide text-white/50">{stat.label}</p>
                        <p className="mt-3 text-4xl font-light tracking-tighter text-white">{stat.value}</p>
                      </div>
                    ))}
                  </div>

                  {meetingsLoading ? (
                    <div className="flex h-64 items-center justify-center rounded-[2rem] border border-white/10 bg-white/5 mt-8">
                      <div className="flex flex-col items-center gap-4 text-white/50">
                        <Loader2 className="h-8 w-8 animate-spin text-sky-400" />
                        <p className="font-light tracking-wide">Syncing Workspace...</p>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-8 animate-in fade-in duration-1000">
                      <MeetingGrid 
                        meetings={hasSmartSearch ? searchedMeetings : searchedMeetings.slice(0, 8)} 
                        onOpenMeeting={setSelectedMeeting} 
                        emptyMessage="No events logged yet. Create a session to begin capturing." 
                      />
                    </div>
                  )}
                </TabsContent>

                <TabsContent value="online" className="focus-visible:outline-none">
                  <MeetingGrid meetings={onlineMeetings} onOpenMeeting={setSelectedMeeting} emptyMessage="No online sessions found." />
                </TabsContent>
                <TabsContent value="offline" className="focus-visible:outline-none">
                  <MeetingGrid meetings={offlineMeetings} onOpenMeeting={setSelectedMeeting} emptyMessage="No offline notes found." />
                </TabsContent>
              </Tabs>
            </div>
          )}
        </main>
      </div>

      <AnimatePresence>
        {selectedMeeting && (
          <motion.div
            initial={{ opacity: 0, x: '100%' }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: '100%' }}
            transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
            className="fixed bottom-0 right-0 top-0 z-50 w-full max-w-[500px] border-l border-white/10 bg-[#0a0a0a]/95 p-8 shadow-[-40px_0_100px_rgba(0,0,0,0.5)] backdrop-blur-3xl"
          >
            <div className="flex h-full flex-col">
              <div className="mb-8 flex items-start justify-between">
                <div>
                  <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-sky-400/10 px-3 py-1.5 text-xs font-semibold text-sky-300 uppercase tracking-widest">
                    {selectedMeeting.platform === 'meet' ? <Globe2 className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                    {selectedMeeting.platform}
                  </div>
                  <h2 className="text-3xl font-medium tracking-tight text-white mb-2">{selectedMeeting.title}</h2>
                  <p className="text-sm font-light text-white/50">{formatDate(selectedMeeting.createdAt)}</p>
                </div>
                <button onClick={() => setSelectedMeeting(null)} className="rounded-full border border-white/10 bg-white/5 p-2.5 text-white/50 hover:bg-white/10 hover:text-white transition-colors">
                  <X className="h-5 w-5" />
                </button>
              </div>

               <div className="flex-1 overflow-y-auto pr-2">
                <div className="space-y-8">
                  <section>
                    <h3 className="mb-4 text-xs font-bold uppercase tracking-[0.2em] text-white/50">Intelligence Brief</h3>
                    <div className="rounded-3xl border border-white/10 bg-black/20 p-6 shadow-inner">
                      <p className="whitespace-pre-wrap text-base font-light leading-relaxed text-white/80">
                        {selectedMeeting.summary || 'Intelligence Processing...'}
                      </p>
                    </div>
                  </section>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
'''
text = app_return_pattern.sub(app_replacement, text)

# Just in case SettingView is messed up from previous replace passes, let's fix SettingsView colors too
text = re.compile(r'function SettingsView\(.*?return\s*\(.*?\)\s*\}', re.DOTALL).sub(
    '''function SettingsView({ session, onUpdatedProfile }) {
  return (
    <div className="max-w-2xl animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="space-y-8">
        <section className="rounded-3xl border border-white/10 bg-white/5 p-8 backdrop-blur-xl shadow-2xl">
          <h2 className="text-2xl font-medium tracking-tight text-white mb-2">Profile Settings</h2>
          <p className="text-sm font-light text-white/50 mb-6">Manage your account details and configuration.</p>
          <div className="space-y-4">
             <div className="rounded-2xl border border-white/10 bg-black/20 p-5">
                <label className="text-xs font-bold uppercase tracking-widest text-white/50">Account Email</label>
                <p className="mt-2 text-lg font-light text-white">{session.user.email}</p>
             </div>
          </div>
        </section>
      </div>
    </div>
  )
}''', text)

with open('src/App.jsx', 'w', encoding='utf-8') as f:
    f.write(text)
