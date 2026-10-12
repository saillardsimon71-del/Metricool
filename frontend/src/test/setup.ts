import '@testing-library/jest-dom/vitest'

// fetch est fourni par jsdom >= 21 ; on évite tout appel réseau réel dans les tests.
if (!globalThis.fetch) {
  globalThis.fetch = (() => Promise.reject(new Error('fetch interdit dans les tests'))) as never
}
