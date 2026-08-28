/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: process.env.NODE_ENV === 'production' 
          ? '/api/:path*' 
          : 'http://127.0.0.1:8000/api/:path*',
      },
      {
        source: '/docs',
        destination: process.env.NODE_ENV === 'production' 
          ? '/docs' 
          : 'http://127.0.0.1:8000/docs',
      },
      {
        source: '/openapi.json',
        destination: process.env.NODE_ENV === 'production' 
          ? '/openapi.json' 
          : 'http://127.0.0.1:8000/openapi.json',
      },
    ];
  },
};

module.exports = nextConfig;
