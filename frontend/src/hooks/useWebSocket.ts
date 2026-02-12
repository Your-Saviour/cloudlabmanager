import { useEffect, useRef, useCallback } from 'react'
import { useAuthStore } from '@/stores/authStore'

interface UseWebSocketOptions {
  url: string
  onMessage: (data: string) => void
  onClose?: () => void
  onError?: (e: Event) => void
  enabled?: boolean
}

export function useWebSocket({ url, onMessage, onClose, onError, enabled = true }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const token = useAuthStore((s) => s.token)

  const send = useCallback((data: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data)
    }
  }, [])

  useEffect(() => {
    if (!enabled || !token) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const fullUrl = `${protocol}//${window.location.host}${url}?token=${token}`
    const ws = new WebSocket(fullUrl)
    wsRef.current = ws

    ws.onmessage = (e) => onMessage(e.data)
    ws.onclose = () => onClose?.()
    ws.onerror = (e) => onError?.(e)

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [url, token, enabled])

  return { send, ws: wsRef }
}
