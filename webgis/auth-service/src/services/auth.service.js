import bcrypt from "bcryptjs";
import prisma from "../prisma.js";
import { AppError } from "../utils/appError.js";
import { signToken } from "../utils/jwt.js";

export class AuthService {
  /**
   * Đăng ký tài khoản người dùng mới (luôn tạo role = USER).
   */
  static async register({ name, email, password }) {
    // 1. Kiểm tra cấu hình bật/tắt đăng ký công khai
    const allowPublicRegister = process.env.ALLOW_PUBLIC_REGISTER !== "false";
    if (!allowPublicRegister) {
      throw new AppError(403, "Tính năng đăng ký tài khoản công khai hiện đang tạm khóa");
    }

    // 2. Chuẩn hóa email
    const normalizedEmail = email.toLowerCase().trim();

    // 3. Kiểm tra email đã tồn tại hay chưa
    const existing = await prisma.user.findUnique({
      where: { email: normalizedEmail },
    });
    if (existing) {
      throw new AppError(409, "Email này đã được sử dụng trong hệ thống");
    }

    // 4. Hash mật khẩu (10 salt rounds)
    const salt = await bcrypt.genSalt(10);
    const hashedPassword = await bcrypt.hash(password, salt);

    // 5. Bỏ qua mọi trường role client gửi, ép buộc luôn luôn là USER
    const newUser = await prisma.user.create({
      data: {
        name: name.trim(),
        email: normalizedEmail,
        password: hashedPassword,
        role: "USER",
      },
      select: {
        id: true,
        name: true,
        email: true,
        role: true,
        createdAt: true,
      },
    });

    // 6. Cấp token ngay sau khi đăng ký
    const token = signToken({ userId: newUser.id, role: newUser.role });

    return {
      user: newUser,
      token,
    };
  }

  /**
   * Đăng nhập tài khoản.
   */
  static async login({ email, password }) {
    const normalizedEmail = email.toLowerCase().trim();

    // 1. Tìm tài khoản theo email
    const user = await prisma.user.findUnique({
      where: { email: normalizedEmail },
    });

    // 2. Kiểm tra tài khoản và mật khẩu
    // Dùng thông báo chung để tránh tiết lộ sự tồn tại của email
    if (!user) {
      throw new AppError(401, "Email hoặc mật khẩu không đúng");
    }

    const isMatch = await bcrypt.compare(password, user.password);
    if (!isMatch) {
      throw new AppError(401, "Email hoặc mật khẩu không đúng");
    }

    // 3. Tạo JWT token chứa { userId, role }
    const token = signToken({ userId: user.id, role: user.role });

    return {
      token,
      user: {
        id: user.id,
        name: user.name,
        email: user.email,
        role: user.role,
      },
    };
  }

  /**
   * Lấy thông tin user hiện tại từ Database.
   */
  static async getMe(userId) {
    const user = await prisma.user.findUnique({
      where: { id: userId },
      select: {
        id: true,
        name: true,
        email: true,
        role: true,
        createdAt: true,
        updatedAt: true,
      },
    });

    if (!user) {
      throw new AppError(404, "Không tìm thấy thông tin người dùng");
    }

    return user;
  }

  /**
   * Tự cập nhật thông tin cá nhân (name, email, đổi mật khẩu).
   * Tuyệt đối không cho đổi role qua endpoint này.
   */
  static async updateMe(userId, { name, email, currentPassword, newPassword }) {
    const user = await prisma.user.findUnique({
      where: { id: userId },
    });

    if (!user) {
      throw new AppError(404, "Người dùng không tồn tại");
    }

    const updateData = {};

    // 1. Cập nhật name
    if (name !== undefined) {
      updateData.name = name.trim();
    }

    // 2. Cập nhật email (nếu thay đổi)
    if (email !== undefined) {
      const normalizedEmail = email.toLowerCase().trim();
      if (normalizedEmail !== user.email) {
        const emailExists = await prisma.user.findUnique({
          where: { email: normalizedEmail },
        });
        if (emailExists) {
          throw new AppError(409, "Email này đã được sử dụng bởi một tài khoản khác");
        }
        updateData.email = normalizedEmail;
      }
    }

    // 3. Đổi mật khẩu
    if (newPassword) {
      if (!currentPassword) {
        throw new AppError(400, "Vui lòng nhập mật khẩu hiện tại để xác nhận đổi mật khẩu");
      }

      const isCurrentMatch = await bcrypt.compare(currentPassword, user.password);
      if (!isCurrentMatch) {
        throw new AppError(400, "Mật khẩu hiện tại không chính xác");
      }

      const salt = await bcrypt.genSalt(10);
      updateData.password = await bcrypt.hash(newPassword, salt);
    }

    // 4. Lưu thay đổi vào CSDL
    const updatedUser = await prisma.user.update({
      where: { id: userId },
      data: updateData,
      select: {
        id: true,
        name: true,
        email: true,
        role: true,
        createdAt: true,
        updatedAt: true,
      },
    });

    return updatedUser;
  }
}
