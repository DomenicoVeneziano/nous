// frontend/src/hooks/useWebSocket.ts
import { useEffect, useRef, useCallback } from 'react';

interface WSEvent {
  type: string;
  data: Record<string, unknown>;
}

type EventHandler = (data: Record<string, unknown>) => void;

export function useWebSocket(handlers: Record<string, EventHandler>, onConnect?: () => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const handlersRef = useRef(handlers);
  const onConnectRef = useRef(onConnect);
  handlersRef.current = handlers;
  onConnectRef.current = onConnect;

  useEffect(() => {
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = localStorage.getItem('nous_token');
    const url = token
      ? `${protocol}//${window.location.host}/ws/scan?token=${encodeURIComponent(token)}`
      : `${protocol}//${window.location.host}/ws/scan`;

    function connect() {
      if (disposed) return;

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (onConnectRef.current) onConnectRef.current();
      };

      ws.onmessage = (event) => {
        try {
          const parsed: WSEvent = JSON.parse(event.data);
          const handler = handlersRef.current[parsed.type];
          if (handler) handler(parsed.data);
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (!disposed) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  return { send };
}
