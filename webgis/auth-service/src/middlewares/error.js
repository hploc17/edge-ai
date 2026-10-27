import { ZodError } from "zod";
import { AppError } from "../utils/appError.js";

export const errorHandler = (err, req, res, next) => {
  console.error(`[ERROR] [${req.method} ${req.originalUrl}]:`, err.message || err);

  // Lỗi do Zod validation
  if (err instanceof ZodError) {
    const errorMsg = err.errors.map((e) => e.message).join(", ");
    return res.status(400).json({
      success: false,
      message: errorMsg,
      errors: err.errors,
    });
  }

  // Lỗi trùng Unique constraint của Prisma (P2002)
  if (err.code === "P2002") {
    const target = err.meta?.target ? ` (${err.meta.target.join(", ")})` : "";
    return res.status(409).json({
      success: false,
      message: `Dữ liệu đã tồn tại trong hệ thống${target}`,
    });
  }

  // Lỗi JWT token
  if (err.name === "JsonWebTokenError") {
    return res.status(401).json({
      success: false,
      message: "Token không hợp lệ hoặc đã bị thay đổi",
    });
  }

  if (err.name === "TokenExpiredError") {
    return res.status(401).json({
      success: false,
      message: "Phiên làm việc đã hết hạn. Vui lòng đăng nhập lại.",
    });
  }

  // Lỗi nghiệp vụ định nghĩa qua AppError
  if (err instanceof AppError) {
    return res.status(err.statusCode).json({
      success: false,
      message: err.message,
    });
  }

  // Lỗi server không lường trước
  const statusCode = err.statusCode || 500;
  const message = process.env.NODE_ENV === "production"
    ? "Đã có lỗi nội bộ máy chủ xảy ra"
    : err.message || "Lỗi nội bộ máy chủ";

  res.status(statusCode).json({
    success: false,
    message,
  });
};
