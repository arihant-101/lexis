/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        // Server-side proxy target. Resolved when `rewrites()` runs at BUILD time,
        // so it must be present then (see Dockerfile ARG/ENV). NOT a NEXT_PUBLIC_*
        // var — this never reaches the browser. In Docker it points at the backend
        // service over the compose network; locally it defaults to localhost.
        destination: `${process.env.INTERNAL_API_URL ?? "http://localhost:8000"}/:path*`,
      },
    ];
  },
  async redirects() {
    // Server-side redirect so `/` returns a real HTTP 307 + Location header
    // (works for curl/health-checks), not just the client-only RSC redirect.
    return [
      { source: "/", destination: "/dashboard", permanent: false },
    ];
  },
};

module.exports = nextConfig;
