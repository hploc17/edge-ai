type MessageHandler = (data: any) => void;

class WebSocketService {
  private ws: WebSocket | null = null;
  private handlers: Set<MessageHandler> = new Set();
  private reconnectTimer: any = null;

  private getUrl(): string {
    const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
    const wsProto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${wsProto}//${host}:8000/ws`;
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      this.ws = new WebSocket(this.getUrl());

      this.ws.onopen = () => {
        console.log("[WS] Connected to WebGIS backend real-time stream");
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handlers.forEach((handler) => handler(data));
        } catch (e) {
          console.error("[WS] Message parsing error:", e);
        }
      };

      this.ws.onclose = () => {
        console.warn("[WS] Disconnected, scheduling auto-reconnect in 3s...");
        this.scheduleReconnect();
      };

      this.ws.onerror = (err) => {
        console.error("[WS] Socket error:", err);
      };
    } catch (e) {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect() {
    if (!this.reconnectTimer) {
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this.connect();
      }, 3000);
    }
  }

  subscribe(handler: MessageHandler) {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }

  send(data: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }
}

export const wsService = new WebSocketService();
