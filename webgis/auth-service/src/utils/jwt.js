import jwt from "jsonwebtoken";

const JWT_SECRET = process.env.JWT_SECRET;
if (!JWT_SECRET) {
  // Không dùng khóa mặc định: khóa lộ trong mã nguồn cho phép giả mạo token bất kỳ
  throw new Error("Thiếu JWT_SECRET trong webgis/auth-service/.env (backend FastAPI dùng chung khóa này).");
}
const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || "7d";

export const signToken = (payload) => {
  return jwt.sign(payload, JWT_SECRET, {
    expiresIn: JWT_EXPIRES_IN,
  });
};

export const verifyToken = (token) => {
  return jwt.verify(token, JWT_SECRET);
};
