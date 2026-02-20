import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

const statusConfig: Record<ConnectionStatus, { color: string; label: string }> = {
  connecting: { color: 'bg-yellow-500', label: 'Connecting...' },
  connected: { color: 'bg-green-500', label: 'Connected' },
  disconnected: { color: 'bg-red-500', label: 'Disconnected' },
  error: { color: 'bg-red-500', label: 'Error' },
}

export default function SSHTerminalPage() {
  const { hostname, ip, user: routeUser } = useParams<{ hostname: string; ip: string; user?: string }>()
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const terminalRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const termRef = useRef<any>(null)
  const fitAddonRef = useRef<any>(null)
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const [sshUser, setSshUser] = useState(routeUser || '')
  const [activeUser, setActiveUser] = useState(routeUser || '')

  const connect = useCallback(async (user: string) => {
    if (!terminalRef.current || !hostname || !token) return

    // Clean up existing connection
    wsRef.current?.close()
    if (termRef.current) {
      termRef.current.dispose()
      termRef.current = null
    }

    const { Terminal } = await import('@xterm/xterm')
    const { FitAddon } = await import('@xterm/addon-fit')
    const { WebLinksAddon } = await import('@xterm/addon-web-links')
    const { Unicode11Addon } = await import('@xterm/addon-unicode11')
    await import('@xterm/xterm/css/xterm.css')

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: '"JetBrains Mono", "Noto Color Emoji", monospace',
      theme: {
        background: '#0a0a12',
        foreground: '#e0e4ef',
        cursor: '#7c3aed',
        selectionBackground: '#7c3aed40',
      },
    })

    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.loadAddon(new WebLinksAddon())
    const unicode11Addon = new Unicode11Addon()
    term.loadAddon(unicode11Addon)
    term.unicode.activeVersion = '11'

    term.open(terminalRef.current!)
    fitAddon.fit()

    termRef.current = term
    fitAddonRef.current = fitAddon

    const userLabel = user ? `${user}@${hostname}` : hostname
    term.writeln(`Connecting to ${userLabel} (${ip})...`)

    setStatus('connecting')

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    let wsUrl = `${proto}//${window.location.host}/api/inventory/server/ssh/${hostname}?token=${token}`
    if (user) {
      wsUrl += `&user=${encodeURIComponent(user)}`
    }
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setStatus('connected')
      term.writeln('Connected.\r\n')

      ws.send(JSON.stringify({
        type: 'resize',
        cols: term.cols,
        rows: term.rows,
      }))
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        switch (msg.type) {
          case 'output':
            term.write(msg.data)
            break
          case 'connected':
            break
          case 'error':
            term.writeln(`\r\n\x1b[31m${msg.message}\x1b[0m`)
            break
        }
      } catch {
        term.write(event.data)
      }
    }

    ws.onclose = () => {
      setStatus('disconnected')
      term.writeln('\r\n\x1b[31mConnection closed.\x1b[0m')
    }

    ws.onerror = () => {
      setStatus('error')
      term.writeln('\r\n\x1b[31mConnection error.\x1b[0m')
    }

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }))
      }
    })

    term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols, rows }))
      }
    })
  }, [hostname, ip, token])

  useEffect(() => {
    connect(activeUser)

    const handleResize = () => {
      fitAddonRef.current?.fit()
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      wsRef.current?.close()
      termRef.current?.dispose()
    }
  }, [activeUser, connect])

  const handleUserKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      setActiveUser(sshUser)
    }
  }

  const statusInfo = statusConfig[status]

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)]">
      <div className="flex items-center gap-3 px-4 py-3 border-b">
        <Button variant="ghost" size="icon" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${statusInfo.color}`} />
          <span className="text-xs text-muted-foreground">{statusInfo.label}</span>
        </div>
        <span className="font-medium text-sm">{hostname}</span>
        <span className="text-xs text-muted-foreground">({ip})</span>
        <div className="flex items-center gap-1 ml-auto">
          <span className="text-xs text-muted-foreground">user:</span>
          <Input
            value={sshUser}
            onChange={(e) => setSshUser(e.target.value)}
            onKeyDown={handleUserKeyDown}
            placeholder="root"
            className="h-7 w-32 text-xs"
          />
        </div>
      </div>
      <div ref={terminalRef} className="flex-1 p-1" />
    </div>
  )
}
