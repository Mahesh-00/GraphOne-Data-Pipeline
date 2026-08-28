import React from 'react';
import { 
  Activity, 
  Database, 
  FileText, 
  Briefcase, 
  Rocket, 
  Package, 
  Newspaper, 
  ExternalLink,
  ShieldCheck,
  CheckCircle2,
  Layers,
  Cpu
} from 'lucide-react';

export default function Dashboard() {
  const stats = [
    { label: 'Research Papers', count: '423', icon: FileText, change: '+100% arXiv Sync' },
    { label: 'Startups Tracked', count: '52', icon: Rocket, change: 'YC & Techstars' },
    { label: 'AI Products', count: '108', icon: Package, change: 'PH & TIAAFT' },
    { label: 'Active AI Jobs', count: '25', icon: Briefcase, change: '24h Fresh' },
    { label: 'News Signals', count: '57', icon: Newspaper, change: 'Real-time' },
    { label: 'Canonical Entities', count: '25', icon: Layers, change: 'Resolved' },
  ];

  const verticals = [
    {
      title: 'Research Papers',
      desc: 'arXiv AI papers with automated GitHub repository discovery and dynamic star tracking.',
      status: 'Live & Ingesting',
      tag: 'RESEARCH_PAPER',
      sources: 'arXiv Atom API, Papers with Code, GitHub REST API',
    },
    {
      title: 'Startups & Ventures',
      desc: 'Leading artificial intelligence venture directory listings with entity canonicalization.',
      status: 'Live & Ingesting',
      tag: 'STARTUP',
      sources: 'YCombinator Directory, Techstars Portfolio',
    },
    {
      title: 'AI Products & Tools',
      desc: 'Launched products, pricing models (Free, Freemium, Paid), and startup mapping.',
      status: 'Live & Ingesting',
      tag: 'PRODUCT',
      sources: 'Product Hunt, There Is An AI For That',
    },
    {
      title: 'AI Jobs & Talent Signals',
      desc: 'Full-time remote machine learning, AI engineering, and data science job postings.',
      status: '24h Freshness Filter',
      tag: 'JOB',
      sources: 'WeWorkRemotely, RemoteOK, AIJobsNet, LinkedIn',
    },
    {
      title: 'AI News & Signals',
      desc: 'High-fidelity full-text articles normalized with strict 24-hour publication windows.',
      status: '24h Freshness Filter',
      tag: 'NEWS',
      sources: 'TechCrunch AI, VentureBeat, Verge, MIT Tech Review',
    },
  ];

  return (
    <div className="min-h-screen bg-[#0B0F19] text-slate-100 flex flex-col justify-between">
      {/* Header */}
      <header className="border-b border-slate-800/80 bg-[#0E1526]/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center font-bold text-white shadow-lg shadow-blue-500/20">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
                GraphOne <span className="text-xs bg-blue-500/10 text-blue-400 font-mono px-2 py-0.5 rounded-full border border-blue-500/20">v1.0 Production</span>
              </h1>
              <p className="text-xs text-slate-400">FrontierAtlas Intelligence Graph Pipeline</p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <a 
              href="/api/health" 
              target="_blank"
              className="text-xs font-mono px-3 py-1.5 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5 hover:bg-emerald-500/20 transition"
            >
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              API Online
            </a>
            <a 
              href="/docs" 
              target="_blank"
              className="text-xs font-medium px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center gap-1 transition"
            >
              API Docs <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 w-full flex-1">
        {/* Banner */}
        <div className="mb-8 p-6 rounded-2xl bg-gradient-to-r from-blue-900/40 via-slate-900 to-indigo-900/30 border border-blue-500/20 relative overflow-hidden shadow-xl">
          <div className="max-w-2xl">
            <h2 className="text-2xl font-bold text-white mb-2">Global AI Intelligence Graph</h2>
            <p className="text-sm text-slate-300 leading-relaxed mb-4">
              Autonomous, fault-tolerant ingestion pipeline continuously capturing, normalizing, and resolving multi-dimensional AI entities across research papers, startups, products, jobs, and news signals.
            </p>
            <div className="flex flex-wrap gap-2 text-xs font-mono">
              <span className="bg-slate-800/80 px-2.5 py-1 rounded text-slate-300 border border-slate-700">Multi-Tier LLM: Groq &rarr; Gemini &rarr; DeepSeek</span>
              <span className="bg-slate-800/80 px-2.5 py-1 rounded text-slate-300 border border-slate-700">Deduplication: SHA-256 Hashing</span>
              <span className="bg-slate-800/80 px-2.5 py-1 rounded text-slate-300 border border-slate-700">Full 6-Tab Google Sheets Export</span>
            </div>
          </div>
        </div>

        {/* Metric Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          {stats.map((stat, i) => {
            const Icon = stat.icon;
            return (
              <div key={i} className="bg-[#111827] border border-slate-800/80 rounded-xl p-4 hover:border-slate-700 transition shadow-sm">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-slate-400">{stat.label}</span>
                  <Icon className="w-4 h-4 text-blue-400" />
                </div>
                <div className="text-2xl font-bold text-white mb-1">{stat.count}</div>
                <div className="text-[11px] text-emerald-400 flex items-center gap-1 font-mono">
                  <CheckCircle2 className="w-3 h-3" /> {stat.change}
                </div>
              </div>
            );
          })}
        </div>

        {/* Verticals Section */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <Database className="w-5 h-5 text-blue-400" /> Monitored AI Verticals & Data Pipelines
            </h3>
            <span className="text-xs text-slate-400 font-mono">5 Verticals + Entity Resolution</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {verticals.map((v, i) => (
              <div key={i} className="bg-[#111827] border border-slate-800/80 rounded-xl p-5 hover:border-blue-500/40 transition flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">{v.tag}</span>
                    <span className="text-[11px] text-emerald-400 font-medium flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> {v.status}
                    </span>
                  </div>
                  <h4 className="text-base font-semibold text-white mb-1.5">{v.title}</h4>
                  <p className="text-xs text-slate-400 leading-relaxed mb-4">{v.desc}</p>
                </div>
                <div className="pt-3 border-t border-slate-800 text-[11px] text-slate-500">
                  <span className="text-slate-400 font-medium">Sources:</span> {v.sources}
                </div>
              </div>
            ))}

            {/* Entity Mapping Card */}
            <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-5 hover:border-emerald-500/40 transition flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">RESOLVER</span>
                  <span className="text-[11px] text-emerald-400 font-medium flex items-center gap-1">
                    <ShieldCheck className="w-3.5 h-3.5" /> Canonical Seed Trie
                  </span>
                </div>
                <h4 className="text-base font-semibold text-white mb-1.5">Deterministic Entity Resolver</h4>
                <p className="text-xs text-slate-400 leading-relaxed mb-4">
                  Normalizes noisy scraped variations (&quot;OpenAI, Inc.&quot; &rarr; &quot;OpenAI&quot;) with a 4-tier match strategy and audit logging.
                </p>
              </div>
              <div className="pt-3 border-t border-slate-800 text-[11px] text-slate-500">
                <span className="text-slate-400 font-medium">Output:</span> Entity Mapping Log (Google Sheets Tab 6)
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 bg-[#0E1526] py-6 text-center text-xs text-slate-500">
        <p>GraphOne / FrontierAtlas Intelligence Platform &copy; 2026. Production Data Intelligence Pipeline.</p>
      </footer>
    </div>
  );
}

