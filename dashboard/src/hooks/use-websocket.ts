'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { io, Socket } from 'socket.io-client'

interface UseWebSocketOptions {
  url?: string
  autoConnect?: boolean
  reconnectionAttempts?: number
  reconnectionDelay?: number
}

interface WebSocketState {
  isConnected: boolean
  lastMessage: any
  error: Error | null
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const {
    url = process.env.NEXT_PUBLIC_WS_URL || 'http://localhost:8000',
    autoConnect = true,
    reconnectionAttempts = 5,
    reconnectionDelay = 1000,
  } = options

  const socketRef = useRef<Socket | null>(null)
  const [state, setState] = useState<WebSocketState>({
    isConnected: false,
    lastMessage: null,
    error: null,
  })

  // Event handlers map
  const eventHandlersRef = useRef<Map<string, Set<(data: any) => void>>>(new Map())

  const connect = useCallback(() => {
    if (socketRef.current?.connected) return

    socketRef.current = io(url, {
      transports: ['websocket'],
      reconnectionAttempts,
      reconnectionDelay,
    })

    socketRef.current.on('connect', () => {
      setState(prev => ({ ...prev, isConnected: true, error: null }))
      console.log('WebSocket connected')
    })

    socketRef.current.on('disconnect', () => {
      setState(prev => ({ ...prev, isConnected: false }))
      console.log('WebSocket disconnected')
    })

    socketRef.current.on('connect_error', (error) => {
      setState(prev => ({ ...prev, error }))
      console.error('WebSocket connection error:', error)
    })

    // Re-attach all event handlers
    eventHandlersRef.current.forEach((handlers, event) => {
      handlers.forEach(handler => {
        socketRef.current?.on(event, handler)
      })
    })
  }, [url, reconnectionAttempts, reconnectionDelay])

  const disconnect = useCallback(() => {
    socketRef.current?.disconnect()
    socketRef.current = null
  }, [])

  const emit = useCallback((event: string, data?: any) => {
    if (socketRef.current?.connected) {
      socketRef.current.emit(event, data)
    } else {
      console.warn('WebSocket not connected, cannot emit:', event)
    }
  }, [])

  const subscribe = useCallback((event: string, handler: (data: any) => void) => {
    // Store handler for reconnection
    if (!eventHandlersRef.current.has(event)) {
      eventHandlersRef.current.set(event, new Set())
    }
    eventHandlersRef.current.get(event)!.add(handler)

    // Attach to socket if connected
    socketRef.current?.on(event, handler)

    // Return unsubscribe function
    return () => {
      eventHandlersRef.current.get(event)?.delete(handler)
      socketRef.current?.off(event, handler)
    }
  }, [])

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect()
    }

    return () => {
      disconnect()
    }
  }, [autoConnect, connect, disconnect])

  return {
    ...state,
    connect,
    disconnect,
    emit,
    subscribe,
    socket: socketRef.current,
  }
}

// Hook for subscribing to real-time updates
export function useRealTimeUpdates<T>(
  event: string,
  initialData: T,
  transform?: (data: any) => T
) {
  const [data, setData] = useState<T>(initialData)
  const { subscribe, isConnected } = useWebSocket()

  useEffect(() => {
    const unsubscribe = subscribe(event, (newData) => {
      setData(transform ? transform(newData) : newData)
    })

    return unsubscribe
  }, [event, subscribe, transform])

  return { data, isConnected }
}
