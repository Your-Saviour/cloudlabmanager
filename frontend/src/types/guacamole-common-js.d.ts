declare module 'guacamole-common-js' {
  export namespace Guacamole {
    class Client {
      constructor(tunnel: Tunnel)
      connect(data?: string): void
      disconnect(): void
      getDisplay(): Display
      sendKeyEvent(pressed: boolean, keysym: number): void
      sendMouseState(state: Mouse.State): void
      onclipboard: ((stream: InputStream, mimetype: string) => void) | null
      onstatechange: ((state: number) => void) | null
      onerror: ((status: Status) => void) | null

      static readonly STATE_IDLE: 0
      static readonly STATE_CONNECTING: 1
      static readonly STATE_WAITING: 2
      static readonly STATE_CONNECTED: 3
      static readonly STATE_DISCONNECTING: 4
      static readonly STATE_DISCONNECTED: 5
    }

    class WebSocketTunnel {
      constructor(url: string)
      onerror: ((status: Status) => void) | null
      onstatechange: ((state: number) => void) | null
    }

    type Tunnel = WebSocketTunnel

    class Display {
      getElement(): HTMLElement
      getWidth(): number
      getHeight(): number
      scale(scale: number): void
      onresize: ((width: number, height: number) => void) | null
    }

    class Mouse {
      constructor(element: HTMLElement)
      onmousedown: ((state: Mouse.State) => void) | null
      onmouseup: ((state: Mouse.State) => void) | null
      onmousemove: ((state: Mouse.State) => void) | null

      static readonly State: {
        new (): Mouse.State
      }
    }

    namespace Mouse {
      class State {
        x: number
        y: number
        left: boolean
        middle: boolean
        right: boolean
        up: boolean
        down: boolean
      }
    }

    class Keyboard {
      constructor(element: HTMLElement | Document)
      onkeydown: ((keysym: number) => boolean | void) | null
      onkeyup: ((keysym: number) => void) | null
    }

    class InputStream {
      onblob: ((data: string) => void) | null
      onend: (() => void) | null
    }

    class Status {
      code: number
      message: string
      isError(): boolean

      static readonly Code: {
        SUCCESS: 0x0000
        UPSTREAM_TIMEOUT: 0x0110
        UPSTREAM_ERROR: 0x0200
        RESOURCE_NOT_FOUND: 0x0204
        RESOURCE_CONFLICT: 0x0209
        UPSTREAM_NOT_FOUND: 0x0210
        SESSION_CONFLICT: 0x0301
        SESSION_TIMEOUT: 0x0308
        SESSION_CLOSED: 0x0309
        CLIENT_UNAUTHORIZED: 0x030D
        CLIENT_FORBIDDEN: 0x030F
      }
    }
  }
}
