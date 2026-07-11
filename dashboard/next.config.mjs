/** @type {import('next').NextConfig} */
const nextConfig = {
  // The API base the server components fetch from (FastAPI via `seismo serve`, or Caddy at /api).
  env: {
    SEISMO_API_BASE: process.env.SEISMO_API_BASE ?? "http://127.0.0.1:8000",
  },
};

export default nextConfig;
