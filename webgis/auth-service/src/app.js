import express from "express";
import cors from "cors";
import helmet from "helmet";
import authRoutes from "./routes/auth.routes.js";
import managerRoutes from "./routes/manager.routes.js";
import { errorHandler } from "./middlewares/error.js";
import { AppError } from "./utils/appError.js";

const app = express();

// 1. Bảo mật HTTP headers bằng Helmet
app.use(helmet());

// 2. Cấu hình CORS
const defaultOrigins = [
  "http://localhost:5173",
  "http://localhost:3000",
  "http://localhost:8000",
  "http://127.0.0.1:5173",
  "http://127.0.0.1:3000",
  "http://127.0.0.1:8000",
];

const corsOriginHandler = (origin, callback) => {
  if (!origin) return callback(null, true);
  if (process.env.CORS_ORIGIN) {
    const custom = process.env.CORS_ORIGIN.split(",").map((s) => s.trim());
    if (custom.includes(origin) || custom.includes("*")) return callback(null, true);
  }
  if (defaultOrigins.includes(origin)) return callback(null, true);
  if (/^https?:\/\/(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.\d+\.\d+\.\d+)(:\d+)?$/.test(origin)) {
    return callback(null, true);
  }
  callback(null, false);
};

app.use(
  cors({
    origin: corsOriginHandler,
    credentials: true,
    methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allowedHeaders: ["Content-Type", "Authorization"],
  })
);

// 3. Body Parser
app.use(express.json());

// 4. Health Check
app.get("/api/health", (req, res) => {
  res.status(200).json({
    status: "healthy",
    service: "WebGIS Auth & Role Management Hub",
    timestamp: new Date().toISOString(),
  });
});

// 5. Đăng ký các Routes
app.use("/api/auth", authRoutes);
app.use("/api/admin/managers", managerRoutes);

// 6. Xử lý 404 cho các route không xác định
app.all("*", (req, res, next) => {
  next(new AppError(404, `Không tìm thấy tài nguyên: ${req.method} ${req.originalUrl}`));
});

// 7. Error Handler tập trung
app.use(errorHandler);

export default app;
