import { AuthService } from "../services/auth.service.js";
import { asyncHandler } from "../utils/asyncHandler.js";
import { registerSchema, loginSchema, updateProfileSchema } from "../utils/validation.js";

export class AuthController {
  static register = asyncHandler(async (req, res) => {
    // Validate bằng Zod
    const validatedData = registerSchema.parse(req.body);

    const result = await AuthService.register(validatedData);

    res.status(201).json({
      success: true,
      message: "Đăng ký tài khoản thành công",
      data: result,
    });
  });

  static login = asyncHandler(async (req, res) => {
    // Validate bằng Zod
    const validatedData = loginSchema.parse(req.body);

    const result = await AuthService.login(validatedData);

    res.status(200).json({
      success: true,
      message: "Đăng nhập thành công",
      data: result,
    });
  });

  static getMe = asyncHandler(async (req, res) => {
    const user = await AuthService.getMe(req.user.userId);

    res.status(200).json({
      success: true,
      data: { user },
    });
  });

  static updateMe = asyncHandler(async (req, res) => {
    // Validate bằng Zod
    const validatedData = updateProfileSchema.parse(req.body);

    const updatedUser = await AuthService.updateMe(req.user.userId, validatedData);

    res.status(200).json({
      success: true,
      message: "Cập nhật thông tin thành công",
      data: { user: updatedUser },
    });
  });
}
