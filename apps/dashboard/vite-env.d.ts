/// <reference types="vite/client" />

// sharp is installed at Vercel build time, not locally
declare module "sharp" {
    const sharp: any;
    export default sharp;
}

interface ImportMetaEnv {
    readonly VITE_SUPABASE_URL: string;
    readonly VITE_SUPABASE_ANON_KEY: string;
    readonly VITE_THREADS_CLIENT_ID: string;
    readonly VITE_THREADS_REDIRECT_URI: string;
    readonly VITE_API_URL?: string | undefined;
    readonly [key: string]: string | undefined;
}

interface ImportMeta {
    readonly env: ImportMetaEnv;
}
