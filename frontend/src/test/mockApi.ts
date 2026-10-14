import { vi } from 'vitest'

type RouteValue = unknown | ((url: URL, init?: RequestInit) => unknown)

export interface RecordedCall { path: string; method: string; body: unknown }

/** Remplace fetch par un routeur déterministe (aucun appel réseau dans les tests). */
export function mockApi(routes: Record<string, RouteValue>) {
  const calls: RecordedCall[] = []
  const stub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://testserver')
    // Plus longue correspondance d'abord : '/api/media/x/validate/y' ne doit pas
    // être capturé par la route générique '/api/media'.
    const key = Object.keys(routes)
      .filter((candidate) => url.pathname.startsWith(candidate))
      .sort((a, b) => b.length - a.length)[0]
    calls.push({ path: url.pathname + url.search, method: init?.method ?? 'GET', body: init?.body ? safeParse(String(init.body)) : undefined })
    if (key === undefined) return jsonResponse(404, { detail: `Route non simulée : ${url.pathname}` })
    const value = routes[key]
    const payload = typeof value === 'function' ? value(url, init) : value
    return jsonResponse(200, payload)
  })
  vi.stubGlobal('fetch', stub)
  return { calls, restore: () => vi.unstubAllGlobals() }
}

const safeParse = (value: string) => {
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

const jsonResponse = (status: number, payload: unknown) =>
  new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } })
