/// <reference types="vite/client" />

declare global {
  interface Window { MonacoEnvironment?: { getWorker: () => Worker } }
  var MonacoEnvironment: { getWorker: () => Worker } | undefined;
}
export {};
