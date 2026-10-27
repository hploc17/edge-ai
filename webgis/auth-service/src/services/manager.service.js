import bcrypt from "bcryptjs";
import prisma from "../prisma.js";
import { AppError } from "../utils/appError.js";

export class ManagerService {
  /**
   * Lấy danh sách tài khoản MANAGER kèm phân trang và tìm kiếm.
   */
  static async listManagers({ page = 1, limit = 10, search = "" }) {
    const pageNum = Math.max(1, parseInt(page, 10) || 1);
    const limitNum = Math.max(1, Math.min(100, parseInt(limit, 10) || 10));
    const skip = (pageNum - 1) * limitNum;

    const where = {
      role: "MANAGER",
    };

    if (search && search.trim()) {
      const searchTerm = search.trim();
      where.OR = [
        { name: { contains: searchTerm, mode: "insensitive" } },
        { email: { contains: searchTerm, mode: "insensitive" } },
      ];
    }

    const [total, managers] = await Promise.all([
      prisma.user.count({ where }),
      prisma.user.findMany({
        where,
        skip,
        take: limitNum,
        orderBy: { createdAt: "desc" },
        select: {
          id: true,
          name: true,
          email: true,
          role: true,
          createdAt: true,
          updatedAt: true,
        },
      }),
    ]);

    return {
      managers,
      pagination: {
        total,
        page: pageNum,
        limit: limitNum,
        totalPages: Math.ceil(total / limitNum),
      },
    };
  }

  /**
   * Tạo tài khoản MANAGER mới.
   * Role luôn luôn bị ép buộc là MANAGER.
   */
  static async createManager({ name, email, password }) {
    const normalizedEmail = email.toLowerCase().trim();

    const existing = await prisma.user.findUnique({
      where: { email: normalizedEmail },
    });
    if (existing) {
      throw new AppError(409, "Email này đã được sử dụng bởi tài khoản khác");
    }

    const salt = await bcrypt.genSalt(10);
    const hashedPassword = await bcrypt.hash(password, salt);

    const newManager = await prisma.user.create({
      data: {
        name: name.trim(),
        email: normalizedEmail,
        password: hashedPassword,
        role: "MANAGER", // Luôn luôn là MANAGER
      },
      select: {
        id: true,
        name: true,
        email: true,
        role: true,
        createdAt: true,
      },
    });

    return newManager;
  }

  /**
   * Cập nhật thông tin tài khoản MANAGER.
   * QUY TẮC AN TOÀN:
   * - Chỉ thao tác trên tài khoản có role = MANAGER.
   * - Nếu ID thuộc ADMIN hoặc USER -> trả 404 hoặc 403.
   * - Tuyệt đối không cho phép nâng quyền lên ADMIN qua API.
   */
  static async updateManager(managerId, { name, email, password }) {
    const targetUser = await prisma.user.findUnique({
      where: { id: managerId },
    });

    if (!targetUser) {
      throw new AppError(404, "Không tìm thấy người dùng");
    }

    // Kiểm tra an toàn: chỉ được thao tác trên MANAGER
    if (targetUser.role !== "MANAGER") {
      throw new AppError(403, "Chỉ được phép thao tác trên tài khoản có vai trò MANAGER");
    }

    const updateData = {};

    if (name !== undefined) {
      updateData.name = name.trim();
    }

    if (email !== undefined) {
      const normalizedEmail = email.toLowerCase().trim();
      if (normalizedEmail !== targetUser.email) {
        const emailExists = await prisma.user.findUnique({
          where: { email: normalizedEmail },
        });
        if (emailExists) {
          throw new AppError(409, "Email này đã được sử dụng");
        }
        updateData.email = normalizedEmail;
      }
    }

    // Đặt lại mật khẩu nếu Admin yêu cầu
    if (password) {
      const salt = await bcrypt.genSalt(10);
      updateData.password = await bcrypt.hash(password, salt);
    }

    const updated = await prisma.user.update({
      where: { id: managerId },
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

    return updated;
  }

  /**
   * Xóa tài khoản MANAGER.
   * QUY TẮC AN TOÀN:
   * - Admin không được xóa chính mình.
   * - Chỉ xóa user có role = MANAGER.
   * - Không xóa user ADMIN hoặc USER qua endpoint này.
   */
  static async deleteManager(adminUserId, managerId) {
    if (adminUserId === managerId) {
      throw new AppError(400, "Bạn không thể tự xóa tài khoản của chính mình");
    }

    const targetUser = await prisma.user.findUnique({
      where: { id: managerId },
    });

    if (!targetUser) {
      throw new AppError(404, "Không tìm thấy tài khoản để xóa");
    }

    if (targetUser.role !== "MANAGER") {
      throw new AppError(403, "Chỉ được phép xóa tài khoản có vai trò MANAGER");
    }

    await prisma.user.delete({
      where: { id: managerId },
    });

    return { message: "Đã xóa tài khoản MANAGER thành công" };
  }
}
