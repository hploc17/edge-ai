/**
 * Middleware Phân quyền & Xác thực JWT
 * 
 * SO SÁNH GIỮA "CHỈ TIN ROLE TRONG TOKEN" VÀ "ĐỐI CHIẾU LẠI DATABASE":
 * - Chỉ tin role trong Token:
 *   + Ưu điểm: Tốc độ cực nhanh, stateless, giảm tải truy vấn cho Database, thích hợp microservices.
 *   + Nhược điểm: Nếu tài khoản bị hạ quyền từ MANAGER xuống USER hoặc bị Admin xóa/khóa,
 *     token cũ vẫn có hiệu lực cho đến khi hết hạn (ví dụ 7 ngày).
 * - Đối chiếu lại Database (Database Verification):
 *   + Ưu điểm: Tuyệt đối an toàn, quyền hạn được cập nhật tức thì (ngay khi bị xóa/hạ role sẽ bị chặn ngay lập tức).
 *   + Nhược điểm: Tốn thêm 1 truy vấn DB trên mỗi request.
 * - KHUYẾN NGHỊ:
 *   + Với các endpoint thông thường (GIS, xem dữ liệu): Chỉ cần verify JWT token để tối ưu hiệu năng.
 *   + Với các endpoint nhạy cảm (ADMIN_ONLY quản lý tài khoản Manager, đổi mật khẩu): BẮT BUỘC đối chiếu
 *     lại CSDL (fresh DB check) để tài khoản bị xóa hoặc thay đổi quyền lập tức mất hiệu lực.
 */

import { AppError } from "../utils/appError.js";
import { verifyToken } from "../utils/jwt.js";
import prisma from "../prisma.js";

// Hằng số phân quyền dùng chung toàn hệ thống
export const STAFF = ["ADMIN", "MANAGER"];
export const ADMIN_ONLY = ["ADMIN"];
export const ALL_ROLES = ["ADMIN", "MANAGER", "USER"];

/**
 * Xác thực Bearer Token từ header Authorization.
 * Gắn thông tin req.user = { userId, role } nếu hợp lệ.
 */
export const authenticate = (req, res, next) => {
  const authHeader = req.headers.authorization;

  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    return next(new AppError(401, "Bạn chưa đăng nhập hoặc thiếu Bearer Token hợp lệ"));
  }

  const token = authHeader.split(" ")[1];
  if (!token) {
    return next(new AppError(401, "Token không đúng định dạng Bearer"));
  }

  try {
    const decoded = verifyToken(token);
    req.user = {
      userId: decoded.userId,
      role: decoded.role,
    };
    next();
  } catch (error) {
    if (error.name === "TokenExpiredError") {
      return next(new AppError(401, "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."));
    }
    return next(new AppError(401, "Token không hợp lệ hoặc sai chữ ký"));
  }
};

/**
 * Kiểm tra role của người dùng có nằm trong allowedRoles hay không.
 * Nếu request chưa qua authenticate thì tự động xác thực trước.
 * 
 * @param {string[]} allowedRoles - Danh sách role được phép truy cập
 */
export const authorizeRoles = (allowedRoles) => {
  return async (req, res, next) => {
    // 1. Tự động xác thực nếu chưa có req.user
    if (!req.user) {
      const authHeader = req.headers.authorization;
      if (!authHeader || !authHeader.startsWith("Bearer ")) {
        return next(new AppError(401, "Yêu cầu đăng nhập để truy cập tài nguyên này"));
      }
      const token = authHeader.split(" ")[1];
      try {
        const decoded = verifyToken(token);
        req.user = {
          userId: decoded.userId,
          role: decoded.role,
        };
      } catch (err) {
        return next(new AppError(401, "Token không hợp lệ hoặc đã hết hạn"));
      }
    }

    // 2. Kiểm tra role trong token có thuộc allowedRoles
    if (!allowedRoles.includes(req.user.role)) {
      return next(
        new AppError(
          403,
          `Bạn không có quyền thực hiện hành động này. Yêu cầu một trong các quyền: [${allowedRoles.join(", ")}]`
        )
      );
    }

    next();
  };
};

/**
 * Middleware đối chiếu lại CSDL để bảo vệ tối đa các route quản trị nhạy cảm (ADMIN_ONLY).
 * Ngăn chặn việc dùng token cũ của tài khoản đã bị xóa hoặc bị hạ quyền.
 */
export const requireFreshDbUser = async (req, res, next) => {
  if (!req.user || !req.user.userId) {
    return next(new AppError(401, "Chưa xác thực người dùng"));
  }

  try {
    const dbUser = await prisma.user.findUnique({
      where: { id: req.user.userId },
      select: { id: true, email: true, name: true, role: true },
    });

    if (!dbUser) {
      return next(new AppError(401, "Tài khoản của bạn không còn tồn tại trên hệ thống"));
    }

    // Cập nhật lại role mới nhất từ CSDL
    req.user.role = dbUser.role;
    req.user.email = dbUser.email;
    req.user.name = dbUser.name;

    next();
  } catch (error) {
    next(error);
  }
};
