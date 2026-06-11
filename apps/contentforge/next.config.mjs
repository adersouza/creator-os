/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  // Allow serving thumbnails from public dir
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
