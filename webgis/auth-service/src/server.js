import dotenv from "dotenv";
import app from "./app.js";
import prisma from "./prisma.js";

dotenv.config();

const PORT = process.env.PORT || 5000;

const server = app.listen(PORT, () => {
  console.log(`[AUTH SERVICE] Node.js Express Auth Server đang chạy tại http://localhost:${PORT}`);
  console.log(`[AUTH SERVICE] CORS cho phép: ${process.env.CORS_ORIGIN || "http://localhost:5173"}`);
});

// Xử lý Graceful Shutdown
const handleShutdown = async (signal) => {
  console.log(`\n[AUTH SERVICE] Nhận tín hiệu ${signal}. Đang đóng các kết nối...`);
  server.close(async () => {
    await prisma.$disconnect();
    console.log("[AUTH SERVICE] Đã đóng server và ngắt kết nối Database hoàn tất.");
    process.exit(0);
  });
};

process.on("SIGINT", () => handleShutdown("SIGINT"));
process.on("SIGTERM", () => handleShutdown("SIGTERM"));
