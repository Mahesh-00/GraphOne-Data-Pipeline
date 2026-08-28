import React from 'react';
import { ArrowLeft, CheckCircle2, Code, ShieldCheck, Zap } from 'lucide-react';
import Link from 'next/link';

export default function DocsPage() {
  const endpoints = [
    {
      method: 'GET',
      path: '/api/health',
      desc: 'System health check and pipeline status indicator.',
      sampleResponse: `{
  "status": "healthy",
  "timestamp": "2026-08-28T18:00:00Z",
  "service": "GraphOne Intelligence Platform",
  "version": "1.0.0"
}`,
    },
    {
      method: 'GET',
      path: '/api/stats',
      desc: 'Real-time database entity counts across all 5 verticals.',
      sampleResponse: `{
  "papers": 453,
  "startups": 52,
  "products": 108,
  "jobs": 25,
  "news": 57,
  "entities_resolved": 25
}`,
    },
    {
      method: 'GET',
      path: '/api/papers',
      desc: 'Paginated research paper entities with arXiv metadata & GitHub stars.',
      sampleResponse: `[
  {
    "arxiv_id": "2608.13522",
    "title": "Vero: Can AI Agents Build Formally Verified Repositories?",
    "github_url": "https://github.com/sunblaze-ucb/vero",
    "github_stars": 8,
    "published_date": "2026-08-13T17:41:27Z"
  }
]`,
    },
    {
      method: 'GET',
      path: '/api/startups',
      desc: 'Paginated AI startup records normalized by deterministic entity resolver.',
      sampleResponse: `[
  {
    "entityName": "Doordash",
    "description": "Restaurant delivery.",
    "source_name": "YCombinator"
  }
]`,
    },
    {
      method: 'GET',
      path: '/api/jobs',
      desc: '24-hour fresh machine learning & AI remote jobs.',
      sampleResponse: `[
  {
    "title": "Staff Software Engineer",
    "company": "Gusto, Inc.",
    "location": "Anywhere in the World",
    "source_name": "WeWorkRemotely"
  }
]`,
    },
  ];

  return (
    <div className="min-h-screen bg-[#0B0F19] text-slate-100 p-6 md:p-12">
      <div className="max-w-4xl mx-auto">
        <Link 
          href="/" 
          className="inline-flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300 font-medium mb-8 transition"
        >
          <ArrowLeft className="w-4 h-4" /> Back to Dashboard
        </Link>

        <div className="border-b border-slate-800 pb-6 mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-blue-600/20 text-blue-400 border border-blue-500/20">
              <Code className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">GraphOne API Documentation</h1>
              <p className="text-sm text-slate-400">FrontierAtlas Intelligence Graph REST API Reference</p>
            </div>
          </div>
          <div className="flex gap-4 mt-4 text-xs font-mono text-slate-400">
            <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Base URL: /api</span>
            <span className="flex items-center gap-1.5"><ShieldCheck className="w-3.5 h-3.5 text-blue-400" /> JSON / REST</span>
            <span className="flex items-center gap-1.5"><Zap className="w-3.5 h-3.5 text-amber-400" /> Version 1.0</span>
          </div>
        </div>

        <div className="space-y-6">
          {endpoints.map((ep, i) => (
            <div key={i} className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-xs font-mono font-bold px-2.5 py-1 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  {ep.method}
                </span>
                <span className="font-mono text-sm font-semibold text-white">{ep.path}</span>
              </div>
              <p className="text-xs text-slate-300 mb-4">{ep.desc}</p>
              
              <div className="bg-[#0B0F19] rounded-lg p-3 border border-slate-800/80">
                <div className="text-[10px] font-mono uppercase text-slate-500 mb-1.5">Example Response (200 OK)</div>
                <pre className="text-xs font-mono text-slate-300 overflow-x-auto whitespace-pre">
                  {ep.sampleResponse}
                </pre>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

