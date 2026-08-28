import { NextResponse } from 'next/server';

export async function GET() {
  return NextResponse.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    service: 'GraphOne Intelligence Platform',
    version: '1.0.0',
    pipelines: {
      research_papers: 'active',
      startups: 'active',
      products: 'active',
      jobs: 'active',
      news: 'active',
      entity_resolution: 'active',
    },
  });
}

