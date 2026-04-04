import re
with open('src/App.jsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix Hero background and text colors to ensure perfect contrast dark mode
content = content.replace('bg-[#0a0a0a]', 'bg-slate-950')
content = content.replace('mix-blend-screen', '')
content = content.replace('bg-[#111]', 'bg-white')
content = content.replace('bg-[#111]/5', 'bg-white/5')
content = content.replace('bg-[#111]/10', 'bg-white/10')
content = content.replace('text-black transition-all hover:scale-[1.02] hover:shadow-[0_0_40px_rgba(255,255,255,0.3)]', 'text-slate-900 transition-all hover:scale-[1.02] hover:shadow-[0_0_40px_rgba(255,255,255,0.3)]')

# Fix 'Get Started Free' button which was accidentally black on black
content = content.replace('className="group relative flex h-16 transform items-center justify-center overflow-hidden rounded-full bg-white px-10 text-lg font-medium text-black', 'className="group relative flex h-16 transform items-center justify-center overflow-hidden rounded-full bg-white px-10 text-lg font-medium text-slate-950')

# Also let's fix the Dashboard radial gradient which is light mode
content = content.replace('bg-[radial-gradient(circle_at_top_left,_#e2e8f0_0%,_#f8fafc_38%,_#eef2ff_100%)]', 'bg-slate-950')

with open('src/App.jsx', 'w', encoding='utf-8') as f:
    f.write(content)
