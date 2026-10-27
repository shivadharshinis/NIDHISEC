import { API_BASE_URL } from '../config'

export class ApiError extends Error {
  readonly status?: number
  /** Field-level validation messages from a 422 response, keyed by field name. */
  readonly fieldErrors: Record<string, string>

  constructor(message: string, status?: number, fieldErrors: Record<string, string> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  timeoutMs?: number
  /** Skip attaching the session token (e.g. health checks, login). */
  anonymous?: boolean
}

// Session wiring, set by AuthProvider. Kept here so every request uses it.
let authToken: string | null = null
let onUnauthorized: (() => void) | null = null

export function setAuthToken(token: string | null) {
  authToken = token
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

function friendlyMessage(message: string): string {
  const cleaned = message.replace(/^Value error, /, '')
  if (cleaned.startsWith('String should match pattern')) return 'Contains characters that are not allowed'
  if (cleaned.startsWith('Extra inputs are not permitted')) return 'This field cannot be set'
  return cleaned
}

function parseError(status: number, payload: unknown): ApiError {
  const detail = (payload as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return new ApiError(detail, status)
  if (Array.isArray(detail)) {
    const fieldErrors: Record<string, string> = {}
    const general: string[] = []
    for (const issue of detail as ValidationIssue[]) {
      const field = issue.loc && issue.loc.length > 1 ? String(issue.loc[issue.loc.length - 1]) : null
      const message = friendlyMessage(issue.msg ?? 'Invalid value')
      if (field && !fieldErrors[field]) fieldErrors[field] = message
      else if (!field) general.push(message)
    }
    return new ApiError(general[0] ?? 'Please correct the highlighted fields', status, fieldErrors)
  }
  return new ApiError(`Request failed with HTTP ${status}`, status)
}

/** Call the NidhiSec API. Throws ApiError on network, timeout or HTTP errors. */
export async function apiRequest<T>(
  path: string,
  { method = 'GET', body, signal, timeoutMs = 15000, anonymous = false }: RequestOptions = {},
): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  const forwardAbort = () => controller.abort()
  signal?.addEventListener('abort', forwardAbort)

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (!anonymous && authToken) headers.Authorization = `Bearer ${authToken}`

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (error) {
    if (timedOut) throw new ApiError(`No response within ${timeoutMs / 1000}s`)
    if (signal?.aborted) throw error
    throw new ApiError('Unable to reach the backend')
  } finally {
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', forwardAbort)
  }

  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && !anonymous && authToken) onUnauthorized?.()
    throw parseError(response.status, payload)
  }
  return payload as T
}

/**
 * Upload multipart form data with progress reporting (fetch cannot report
 * upload progress, so this uses XMLHttpRequest).
 */
export function apiUpload<T>(
  path: string,
  formData: FormData,
  { onProgress, timeoutMs = 120000 }: { onProgress?: (fraction: number) => void; timeoutMs?: number } = {},
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE_URL}${path}`)
    xhr.setRequestHeader('Accept', 'application/json')
    if (authToken) xhr.setRequestHeader('Authorization', `Bearer ${authToken}`)
    xhr.timeout = timeoutMs
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total)
    }
    xhr.onload = () => {
      let payload: unknown = null
      try {
        payload = JSON.parse(xhr.responseText)
      } catch {
        // non-JSON body; handled below
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(payload as T)
      if (xhr.status === 401 && authToken) onUnauthorized?.()
      reject(parseError(xhr.status, payload))
    }
    xhr.onerror = () => reject(new ApiError('Unable to reach the backend'))
    xhr.ontimeout = () => reject(new ApiError(`No response within ${timeoutMs / 1000}s`))
    xhr.send(formData)
  })
}

/** Download a file through an authenticated endpoint and hand it to the browser as a file save. */
export async function apiDownload(path: string, filename: string): Promise<void> {
  const headers: Record<string, string> = {}
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { headers })
  } catch {
    throw new ApiError('Unable to reach the backend')
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    if (response.status === 401 && authToken) onUnauthorized?.()
    throw parseError(response.status, payload)
  }
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

export function apiGet<T>(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<T> {
  return apiRequest<T>(path, { ...options, method: 'GET' })
}

/** Build a query string, skipping empty values. Arrays become repeated keys. */
export function toQuery(params: Record<string, string | number | boolean | string[] | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '' || value === false) continue
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v))
    else search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}
