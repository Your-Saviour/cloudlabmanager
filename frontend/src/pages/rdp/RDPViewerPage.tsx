import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, ChevronDown, Maximize, RotateCcw, Monitor } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

interface RDPUser {
  username: string
  source: string
  domain: string
}

const statusConfig: Record<ConnectionStatus, { color: string; label: string }> = {
  connecting: { color: 'bg-yellow-500', label: 'Connecting...' },
  connected: { color: 'bg-green-500', label: 'Connected' },
  disconnected: { color: 'bg-red-500', label: 'Disconnected' },
  error: { color: 'bg-red-500', label: 'Error' },
}

export default function RDPViewerPage() {
  const { hostname, ip } = useParams<{ hostname: string; ip: string }>()
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const displayRef = useRef<HTMLDivElement>(null)
  const clientRef = useRef<any>(null)
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const [rdpUsers, setRdpUsers] = useState<RDPUser[]>([])
  const [selectedUser, setSelectedUser] = useState('')
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)

  // Fetch available RDP users
  useEffect(() => {
    if (!hostname || !token) return
    fetch(`/api/inventory/server/${hostname}/rdp-users`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.users?.length) {
          setRdpUsers(data.users)
          if (!selectedUser) {
            setSelectedUser(data.users[0].username)
          }
        }
      })
      .catch(() => {})
  }, [hostname, token])

  const connect = useCallback(async (user: string) => {
    if (!displayRef.current || !hostname || !token) return

    // Clean up existing connection
    if (clientRef.current) {
      try { clientRef.current.disconnect() } catch {}
      clientRef.current = null
    }
    // Clear display container
    if (displayRef.current) {
      displayRef.current.innerHTML = ''
    }

    setStatus('connecting')

    try {
      const Guacamole = await import('guacamole-common-js')

      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const container = displayRef.current!
      const width = container.clientWidth
      const height = container.clientHeight
      const dpi = Math.round(window.devicePixelRatio * 96)

      let wsUrl = `${proto}//${window.location.host}/api/inventory/server/rdp/${hostname}?token=${token}&width=${width}&height=${height}&dpi=${dpi}`
      if (user) {
        wsUrl += `&user=${encodeURIComponent(user)}`
      }

      const tunnel = new Guacamole.Guacamole.WebSocketTunnel(wsUrl)
      const client = new Guacamole.Guacamole.Client(tunnel)
      clientRef.current = client

      const display = client.getDisplay()
      const displayElement = display.getElement()
      displayElement.style.cursor = 'default'
      container.appendChild(displayElement)

      // State change handler
      client.onstatechange = (state: number) => {
        switch (state) {
          case 1: // CONNECTING
            setStatus('connecting')
            break
          case 3: // CONNECTED
            setStatus('connected')
            break
          case 5: // DISCONNECTED
            setStatus('disconnected')
            break
        }
      }

      client.onerror = (status: any) => {
        console.error('Guacamole error:', status?.message || status)
        setStatus('error')
      }

      tunnel.onerror = (status: any) => {
        console.error('Tunnel error:', status?.message || status)
        setStatus('error')
      }

      // Mouse input
      const mouse = new Guacamole.Guacamole.Mouse(displayElement)
      mouse.onmousedown = mouse.onmouseup = mouse.onmousemove = (state: any) => {
        client.sendMouseState(state)
      }

      // Keyboard input
      const keyboard = new Guacamole.Guacamole.Keyboard(document)
      keyboard.onkeydown = (keysym: number) => {
        client.sendKeyEvent(true, keysym)
        return false // prevent default browser handling
      }
      keyboard.onkeyup = (keysym: number) => {
        client.sendKeyEvent(false, keysym)
      }

      // Auto-scale display to fit container
      display.onresize = () => {
        scaleDisplay(display, container)
      }

      // Connect with display parameters
      client.connect(`width=${width}&height=${height}&dpi=${dpi}`)

    } catch (err) {
      console.error('Failed to initialize RDP:', err)
      setStatus('error')
    }
  }, [hostname, token])

  // Scale display to fit container
  function scaleDisplay(display: any, container: HTMLElement) {
    if (!display || !container) return
    const displayWidth = display.getWidth()
    const displayHeight = display.getHeight()
    if (!displayWidth || !displayHeight) return

    const containerWidth = container.clientWidth
    const containerHeight = container.clientHeight

    const scaleX = containerWidth / displayWidth
    const scaleY = containerHeight / displayHeight
    const scale = Math.min(scaleX, scaleY)

    display.scale(scale)
  }

  // Connect when user changes
  useEffect(() => {
    if (selectedUser) {
      connect(selectedUser)
    }

    return () => {
      if (clientRef.current) {
        try { clientRef.current.disconnect() } catch {}
        clientRef.current = null
      }
    }
  }, [selectedUser, connect])

  // Handle window resize
  useEffect(() => {
    const handleResize = () => {
      if (clientRef.current && displayRef.current) {
        const display = clientRef.current.getDisplay()
        scaleDisplay(display, displayRef.current)
      }
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // Fullscreen toggle
  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      displayRef.current?.parentElement?.requestFullscreen()
      setIsFullscreen(true)
    } else {
      document.exitFullscreen()
      setIsFullscreen(false)
    }
  }

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', handler)
    return () => document.removeEventListener('fullscreenchange', handler)
  }, [])

  const handleSelectUser = (username: string) => {
    setSelectedUser(username)
    setDropdownOpen(false)
  }

  const handleReconnect = () => {
    if (selectedUser) {
      connect(selectedUser)
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
        <Monitor className="h-4 w-4 text-muted-foreground" />
        <span className="font-medium text-sm">{hostname}</span>
        <span className="text-xs text-muted-foreground">({ip})</span>

        <div className="flex items-center gap-1 ml-auto">
          <span className="text-xs text-muted-foreground">user:</span>
          <Popover open={dropdownOpen} onOpenChange={setDropdownOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="h-7 text-xs gap-1">
                {selectedUser || 'Select user'}
                <ChevronDown className="h-3 w-3" />
              </Button>
            </PopoverTrigger>
            {rdpUsers.length > 0 && (
              <PopoverContent align="end" className="w-52 p-1">
                {rdpUsers.map((u) => (
                  <button
                    key={u.username}
                    onClick={() => handleSelectUser(u.username)}
                    className="flex items-center gap-2 w-full px-2 py-1.5 text-xs rounded hover:bg-accent text-left"
                  >
                    <span className="truncate">{u.username}</span>
                    {u.domain && (
                      <span className="ml-auto text-[10px] text-muted-foreground">{u.domain}</span>
                    )}
                  </button>
                ))}
              </PopoverContent>
            )}
          </Popover>

          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={handleReconnect} title="Reconnect">
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleFullscreen} title="Fullscreen">
            <Maximize className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      <div
        ref={displayRef}
        className="flex-1 bg-black overflow-hidden flex items-center justify-center"
        style={{ minHeight: 0 }}
      />
    </div>
  )
}
