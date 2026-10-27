import rateLimit from "express-rate-limit";

// Rate limiter cho đăng nhập: tối đa 10 lần thử trong 15 phút để chống brute-force
export const loginRateLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    success: false,
    message: "Bạn đã thử đăng nhập quá nhiều lần. Vui lòng thử lại sau 15 phút.",
  },
});

// Rate limiter cho đăng ký: tối đa 5 tài khoản trong 15 phút từ 1 IP
export const registerRateLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 5,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    success: false,
    message: "Đã vượt quá giới hạn tạo tài khoản mới. Vui lòng thử lại sau.",
  },
});

// Rate limiter cho snapshot công khai (gợi ý 1 request / 10s / IP)
export const snapshotRateLimiter = rateLimit({
  windowMs: 10 * 1000,
  max: 1,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    success: false,
    message: "Yêu cầu chụp snapshot quá nhanh. Giới hạn 1 lần chụp mỗi 10 giây.",
  },
});
