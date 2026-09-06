/**
 * Desktop LocalHostPort adapter.
 *
 * The Vue renderer imports this boundary rather than the transport module
 * directly. It currently delegates to the loopback FastAPI sidecar; the
 * operation names and result types are the same ones used by the Android
 * embedded-Python adapter.
 */
export * from './api'
