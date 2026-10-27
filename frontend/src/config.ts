export const APP_NAME = 'NidhiSec'
export const APP_DESCRIPTION = 'AICTE Security Deposit / FDR Management Portal'

const DEFAULT_API_BASE_URL = 'http://localhost:8000/api'

/** Backend API base URL, configurable through VITE_API_BASE_URL. No trailing slash. */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/+$/, '')
