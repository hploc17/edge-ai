type MessageHandler = (data: any) => void;
type ReconnectHandler = () => void;

class WebSocketService {
  private ws: WebSocket | null = null;
  private handlers: Set<MessageHandler> = new Set();
  private reconnectHandlers: Set<ReconnectHandler> = new Set();
  private reconnectTimer: any = null;

  private getUrl(): string {
    const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
    const wsProto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
    const token = typeof window !== "undefined" ? localStorage.getItem("webgis_auth_token") : null;
    const authParam = token ? `?token=${encodeURIComponent(token)}` : "";
    return `${wsProto}//${host}:8000/ws${authParam}`;
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

        // Tự động xác thực quyền hạn ngay sau khi socket mở (Fix D6)
        const token = typeof window !== "undefined" ? localStorage.getItem("webgis_auth_token") : null;
        if (token) {
          this.authenticate(token);
        }

        // Kích hoạt re-sync dữ liệu khi kết nối lại thành công (Fix D4)
        this.reconnectHandlers.forEach((cb) => {
          try {
            cb();
          } catch (e) {
            console.error("[WS] Reconnect sync error:", e);
          }
        });
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

  authenticate(token: string) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.send({ type: "authenticate", token });
    }
  }

  deauthenticate() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.send({ type: "authenticate", token: "" });
    }
  }

  onReconnect(callback: ReconnectHandler) {
    this.reconnectHandlers.add(callback);
    return () => {
      this.reconnectHandlers.delete(callback);
    };
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
