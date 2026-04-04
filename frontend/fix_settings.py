import re
with open('src/App.jsx', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'function SettingsView\(.*?(?=export default function App)', re.DOTALL)
replacement = '''function SettingsView({ session, onUpdatedProfile }) {
  return (
    <div className="max-w-2xl animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="space-y-8">
        <section className="rounded-3xl border border-white/10 bg-white/5 p-8 backdrop-blur-xl shadow-2xl">
          <h2 className="text-2xl font-medium tracking-tight text-white mb-2">Profile Settings</h2>
          <p className="text-sm font-light text-white/50 mb-6">Manage your account details and configuration.</p>
          <div className="space-y-4">
             <div className="rounded-2xl border border-white/10 bg-black/20 p-5">
                <label className="text-xs font-bold uppercase tracking-widest text-white/50">Account Email</label>
                <p className="mt-2 text-lg font-light text-white">{session?.user?.email || 'N/A'}</p>
             </div>
          </div>
        </section>
      </div>
    </div>
  )
}

'''
content = pattern.sub(replacement, content)
with open('src/App.jsx', 'w', encoding='utf-8') as f:
    f.write(content)
