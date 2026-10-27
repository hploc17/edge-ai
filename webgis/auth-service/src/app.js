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
const corsOrigins = process.env.CORS_ORIGIN
  ? process.env.CORS_ORIGIN.split(",").map((s) => s.trim())
  : ["http://localhost:5173", "http://localhost:8000"];

app.use(
  cors({
    origin: corsOrigins,
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
