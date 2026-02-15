import { useEffect, useRef, useState, useCallback } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { RotateCw } from 'lucide-react'

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'

interface SSHTerminalModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  hostname: string
  ip: string
  user?: string
}

export function SSHTerminalModal({ open, onOpenChange, hostname, ip, user = 'root' }: SSHTerminalModalProps) {
  const termRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<any>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitAddonRef = useRef<any>(null)
  const token = useAuthStore((s) => s.token)
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const [connectKey, setConnectKey] = useState(0)

  const connect = useCallback(async () => {
    if (!termRef.current || !hostname || !token) return

    // Clean up existing connection
    wsRef.current?.close()
    if (terminalRef.current) {
      terminalRef.current.dispose()
      terminalRef.current = null
    }

    const { Terminal } = await import('@xterm/xterm')
    const { FitAddon } = await import('@xterm/addon-fit')
    const { WebLinksAddon } = await import('@xterm/addon-web-links')
    await import('@xterm/xterm/css/xterm.css')

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: '"JetBrains Mono", monospace',
      theme: {
        background: '#0a0a0f',
        foreground: '#e0e0e8',
        cursor: '#7c3aed',
        selectionBackground: '#7c3aed40',
      },
    })

    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.loadAddon(new WebLinksAddon())

    term.open(termRef.current)
    fitAddon.fit()

    terminalRef.current = term
    fitAddonRef.current = fitAddon

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
            setStatus('disconnected')
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
      setStatus('disconnected')
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
  }, [hostname, token, user, connectKey])

  useEffect(() => {
    if (!open) return

    // Small delay to ensure the dialog DOM is rendered before opening terminal
    const timer = setTimeout(() => connect(), 50)

    return () => {
      clearTimeout(timer)
      wsRef.current?.close()
      if (terminalRef.current) {
        terminalRef.current.dispose()
        terminalRef.current = null
      }
    }
  }, [open, connect])

  // Handle resize when dialog is open
  useEffect(() => {
    if (!open) return

    const handleResize = () => fitAddonRef.current?.fit()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl h-[70vh] flex flex-col p-0 gap-0 [&>button:last-child]:text-white [&>button:last-child]:hover:text-white/80">
        {/* Header bar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-card rounded-t-lg">
          <div className="flex items-center gap-2">
            <span className={cn(
              'h-2 w-2 rounded-full',
              status === 'connected' && 'bg-green-500',
              status === 'connecting' && 'bg-yellow-500 animate-pulse',
              status === 'disconnected' && 'bg-red-500',
            )} />
            <span className="text-sm font-mono">{user}@{hostname}</span>
            <span className="text-xs text-muted-foreground">({ip})</span>
          </div>
          {status === 'disconnected' && (
            <Button
              variant="ghost"
              size="sm"
              className="text-xs h-7 mr-6"
              onClick={() => setConnectKey((k) => k + 1)}
            >
              <RotateCw className="mr-1.5 h-3 w-3" /> Reconnect
            </Button>
          )}
        </div>
        {/* Terminal area */}
        <div ref={termRef} className="flex-1 min-h-0 bg-[#0a0a0f] rounded-b-lg" />
      </DialogContent>
    </Dialog>
  )
}
